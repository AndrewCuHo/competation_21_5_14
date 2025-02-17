import sys

# from lib.loss.bi_tempere_loss import bi_tempered_logistic_loss
# from lib.loss.symmetric_CE_loss import SymmetricCrossEntropy
# from lib.loss.label_smoothing_loss import LabelSmoothingCrossEntropy
import main._init_paths
from lib.loss import *
from lib.dataset.imbalance_cassava import IMBALANCECASSAVA
from lib.config.mydefault import _C as cfg
from lib.config.mydefault import update_config
from lib.utils.utils import (
    create_logger,
    get_optimizer,
    get_scheduler,
    get_model,
    get_category_list,
)
from lib.core.function import train_model, valid_model
from lib.core.combiner import Combiner

import torch
import os, shutil
from torch.utils.data import DataLoader
import argparse
import warnings
import click
from tensorboardX import SummaryWriter
import torch.backends.cudnn as cudnn
import ast
import pickle
import torchvision.transforms as transforms


def parse_args():
    parser = argparse.ArgumentParser(description="codes for sleep stage classification")

    parser.add_argument(
        "--cfg",
        help="decide which cfg to use",
        required=False,
        default="../configs/sleep.yaml",
        type=str,
    )
    parser.add_argument(
        "--ar",
        help="decide whether to use auto resume",
        type=ast.literal_eval,
        dest='auto_resume',
        required=False,
        default=True,
    )

    parser.add_argument(
        "opts",
        help="modify config options using the command-line",
        default=None,
        nargs=argparse.REMAINDER,
    )

    args = parser.parse_args()
    return args


if __name__ == "__main__":
    DIR_CV = ['G:/user/BBN/AllC4/', 'G:/user/BBN/AllF4/', 'G:/user/BBN/AllO1/','G:/user/BBN/TestC4/', 'G:/user/BBN/TestF4/', 'G:/user/BBN/TestO1/',
              'G:/user/BBN/PlusC4/', 'G:/user/BBN/PlusF4/', 'G:/user/BBN/PlusO1/']
    DIR_CV_Eval = ['G:/user/BBN/eval1/', 'G:/user/BBN/eval2/', 'G:/user/BBN/eval3/']
    target_names = ['class 0', 'class 1', 'class 2', 'class 3', 'class 4']
    GPU_ID = '0'
    K_FOLD = [4, 3, 2, 1, 0]
    RandomAugment = True

    os.environ["CUDA_VISIBLE_DEVICES"] = GPU_ID
    args = parse_args()
    update_config(cfg, args)
    logger, log_file = create_logger(cfg)
    warnings.filterwarnings("ignore")
    cudnn.benchmark = True
    auto_resume = args.auto_resume

    l_formulas = {
        'parabolic_decay': '1 - ((self.epoch - 1) / self.div_epoch) ** 2',  # parabolic decay
        # 'linear_decay': '1 - (self.epoch-1) / self.div_epoch',  # linear decay
        # 'cosine_decay': 'math.cos((self.epoch-1) / self.div_epoch * math.pi /2)',  # cosine decay
        # 'beta_distribution': 'np.random.beta(self.alpha, self.alpha)',  # beta distribution
        # 'fix_0.5': '0.5',  # fix
        # 'seperated_stage': '1 if self.epoch <= 25 else 0',  # seperated stage
        # 'parabolic_increment': '1 - (1 - ((self.epoch - 1) / self.div_epoch) ** 2) * 1',  # parabolic increment
    }

    for k in K_FOLD:
        for l_name, l_formula in l_formulas.items():
            print('fold_' + str(k) + f' {l_name} is running...')
            train_label_dir = DIR_CV
            val_label_dir = DIR_CV_Eval
            if RandomAugment:
                train_set = IMBALANCECASSAVA(train_label_dir, cfg, mode="train", transform_name="RandomAugment")
            else:
                train_set = IMBALANCECASSAVA(train_label_dir, cfg, mode="train", transform_name="light_augment")

            valid_set = IMBALANCECASSAVA(val_label_dir, cfg, mode="valid", transform_name=None)

            annotations = train_set.get_annotations()
            num_classes = train_set.get_num_classes()
            device = torch.device("cpu" if cfg.CPU_MODE else "cuda")

            # 每个类图像个数   所有标签的列表
            num_class_list, cat_list = get_category_list(annotations, num_classes, cfg)

            para_dict = {
                "num_classes": num_classes,
                "num_class_list": num_class_list,
                "cfg": cfg,
                "device": device,
            }

            criterion = {
                'CrossEntropy': lambda: CrossEntropy(para_dict=para_dict),
                'CSCE': lambda: CSCE(para_dict=para_dict),
                'LDAMLoss': lambda: LDAMLoss(para_dict=para_dict),
                'SymmetricCrossEntropy': lambda: SymmetricCrossEntropy(alpha=0.1, beta=1.0, num_classes=5),
                # 'bi_tempered_logistic_loss': lambda: bi_tempered_logistic_loss(activations, labels, t1, t2, label_smoothing=0.0, num_iters=5),
                'LabelSmoothingCrossEntropy': lambda: LabelSmoothingCrossEntropy(),
            }[cfg.LOSS.LOSS_TYPE]()

            # CrossEntropy
            # criterion = eval(cfg.LOSS.LOSS_TYPE)(para_dict=para_dict)
            epoch_number = cfg.TRAIN.MAX_EPOCH

            # ----- BEGIN MODEL BUILDER -----
            model = get_model(cfg, num_classes, device, logger)
            # 是否是多卡训练的预模型
            # model = torch.nn.DataParallel(model)
            # cudnn.benchmark = True

            combiner = Combiner(cfg, device, l_formula)
            optimizer = get_optimizer(cfg, model)
            scheduler = get_scheduler(cfg, optimizer)
            # ----- END MODEL BUILDER -----

            # train_dataloader = torch.utils.data.DataLoader(train_set, batch_size=2, shuffle=True, num_workers=2)
            # val_dataloader = torch.utils.data.DataLoader(val_set, batch_size=2, shuffle=False, num_workers=2)
            trainLoader = DataLoader(
                train_set,
                batch_size=cfg.TRAIN.BATCH_SIZE,
                shuffle=cfg.TRAIN.SHUFFLE,
                num_workers=cfg.TRAIN.NUM_WORKERS,
                pin_memory=cfg.PIN_MEMORY,
                drop_last=True
            )

            validLoader = DataLoader(
                valid_set,
                batch_size=cfg.TEST.BATCH_SIZE,
                shuffle=False,
                num_workers=cfg.TEST.NUM_WORKERS,
                pin_memory=cfg.PIN_MEMORY,
            )

            # close loop
            model_dir = os.path.join(cfg.OUTPUT_DIR, cfg.NAME, f"fold_{k}_alpha_{l_name}", "models")
            code_dir = os.path.join(cfg.OUTPUT_DIR, cfg.NAME, f"fold_{k}_alpha_{l_name}", "codes")
            tensorboard_dir = (
                os.path.join(cfg.OUTPUT_DIR, cfg.NAME, f"fold_{k}_alpha_{l_name}", "tensorboard")
                if cfg.TRAIN.TENSORBOARD.ENABLE
                else None
            )

            if not os.path.exists(model_dir):
                os.makedirs(model_dir)
            else:
                logger.info(
                    "This directory has already existed, Please remember to modify your cfg.NAME"
                )
                if not click.confirm(
                        "\033[1;31;40mContinue and override the former directory?\033[0m",
                        default=False,
                ):
                    exit(0)
                shutil.rmtree(code_dir)
                if tensorboard_dir is not None and os.path.exists(tensorboard_dir):
                    shutil.rmtree(tensorboard_dir)
            print("=> output model will be saved in {}".format(model_dir))
            this_dir = os.path.dirname(__file__)
            ignore = shutil.ignore_patterns(
                "*.pyc", "*.so", "*.out", "*pycache*", "*.pth", "*build*", "*output*", "*datasets*", "*data*"
            )
            shutil.copytree(os.path.join(this_dir, ".."), code_dir, ignore=ignore)

            if tensorboard_dir is not None:
                dummy_input = torch.rand((1, 3) + (cfg.INPUT_SIZE, cfg.INPUT_SIZE)).to(device)
                writer = SummaryWriter(log_dir=tensorboard_dir)
                #writer.add_graph(model if cfg.CPU_MODE else model.module, (dummy_input,))
            else:
                writer = None

            best_result, best_epoch, start_epoch = 0, 0, 1
            # ----- BEGIN RESUME ---------
            all_models = os.listdir(model_dir)
            if len(all_models) <= 1 or auto_resume == False:
                auto_resume = False
            else:
                all_models.remove("best_model.pth")
                resume_epoch = max([int(name.split(".")[0].split("_")[-1]) for name in all_models])
                resume_model_path = os.path.join(model_dir, "epoch_{}.pth".format(resume_epoch))

            if cfg.RESUME_MODEL != "" or auto_resume:
                if cfg.RESUME_MODEL == "":
                    resume_model = resume_model_path
                else:
                    resume_model = cfg.RESUME_MODEL if '/' in cfg.RESUME_MODEL else os.path.join(model_dir,
                                                                                                 cfg.RESUME_MODEL)
                logger.info("Loading checkpoint from {}...".format(resume_model))
                checkpoint = torch.load(
                    resume_model, map_location="cpu" if cfg.CPU_MODE else "cuda"
                )
                if cfg.CPU_MODE:
                    model.load_model(resume_model)
                else:
                    model.module.load_model(resume_model)
                if cfg.RESUME_MODE != "state_dict":
                    optimizer.load_state_dict(checkpoint['optimizer'])
                    scheduler.load_state_dict(checkpoint['scheduler'])
                    start_epoch = checkpoint['epoch'] + 1
                    best_result = checkpoint['best_result']
                    best_epoch = checkpoint['best_epoch']
            # ----- END RESUME ---------

            logger.info(
                "-------------------Train start :{}  {}  {}-------------------".format(
                    cfg.BACKBONE.TYPE, cfg.MODULE.TYPE, cfg.TRAIN.COMBINER.TYPE
                )
            )

            for epoch in range(start_epoch, epoch_number + 1):
                scheduler.step()
                train_acc, train_loss = train_model(
                    trainLoader,
                    model,
                    epoch,
                    epoch_number,
                    optimizer,
                    combiner,
                    l_formula,
                    criterion,
                    cfg,
                    logger,
                    writer=writer,
                )
                lr = optimizer.param_groups[0]['lr']
                writer.add_scalar('learning_rate', lr, epoch)

                loss_dict, acc_dict = {"train_loss": train_loss}, {"train_acc": train_acc}

                # validation
                if cfg.VALID_STEP != -1 and epoch % cfg.VALID_STEP == 0:
                    valid_acc, valid_loss, result_epoch = valid_model(
                        validLoader, epoch, model, cfg, criterion, logger, device, target_names, writer=writer
                    )
                    loss_dict["valid_loss"], acc_dict["valid_acc"] = valid_loss, valid_acc
                    if valid_acc > best_result:
                        best_result, best_epoch = valid_acc, epoch
                        torch.save({
                            'state_dict': model.state_dict(),
                            # 'state_dict': model.module.state_dict(),
                            'epoch': epoch,
                            'best_result': best_result,
                            'best_epoch': best_epoch,
                            'scheduler': scheduler.state_dict(),
                            'optimizer': optimizer.state_dict(),
                        }, os.path.join(model_dir, f"best_model_{best_epoch}_{valid_acc}.pth")
                        )
                    logger.info(
                        "--------------Best_Epoch:{:>3d}    Best_Acc:{:>5.2f}%--------------".format(
                            best_epoch, best_result * 100
                        )
                    )

                # save checkpoint
                model_save_path = os.path.join(model_dir, "epoch_{}_{}.pth".format(epoch, valid_acc))
                if epoch % cfg.SAVE_STEP == 0:
                    torch.save({
                        'state_dict': model.state_dict(),
                        'epoch': epoch,
                        'best_result': best_result,
                        'best_epoch': best_epoch,
                        'scheduler': scheduler.state_dict(),
                        'optimizer': optimizer.state_dict()
                    }, model_save_path)

                if cfg.TRAIN.TENSORBOARD.ENABLE:
                    writer.add_scalars("scalar/acc", acc_dict, epoch)
                    writer.add_scalars("scalar/loss", loss_dict, epoch)
                    writer.add_scalar("scalar/alpha", combiner.getL(), epoch)
                    writer.add_scalar('ACC/val', result_epoch['accuracy'], epoch)
                    for metric in ['precision', 'recall', 'f1-score']:
                        writer.add_scalars(f'Metrics/{metric}',
                                           {target_name: result_epoch[target_name][metric] for target_name in
                                            target_names},
                                           epoch)
            if cfg.TRAIN.TENSORBOARD.ENABLE:
                writer.close()
            logger.info(
                "-------------------Train Finished :{}-------------------".format(cfg.NAME)
            )
