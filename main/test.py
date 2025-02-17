import main._init_paths
from lib.net.network import Network
from lib.config.mydefault import _C as cfg, update_config
#from lib.dataset import *
from lib.dataset.imbalance_cassava import IMBALANCECASSAVA
import numpy as np
import torch
import os
from torch.utils.data import DataLoader
from tqdm import tqdm
import argparse
from lib.core.evaluate import FusionMatrix, AverageMeter, accuracy
from sklearn.metrics import classification_report
import pandas as pd
import pickle
from cailiao_1 import make_competation


def parse_args():
    parser = argparse.ArgumentParser(description="sleep evaluation")

    parser.add_argument(
        "--cfg",
        help="decide which cfg to use",
        required=False,
        default="../configs/sleep.yaml",
        type=str,
    )
    parser.add_argument(
        "opts",
        help="Modify config options using the command-line",
        default=None,
        nargs=argparse.REMAINDER,
    )

    args = parser.parse_args()
    return args


def valid_model(dataLoader, model, cfg, device, num_classes, test_mode=False, save_path=None):
    result_list = []
    pbar = tqdm(total=len(dataLoader))
    model.eval()
    top1_count, top2_count, top3_count, index, fusion_matrix = (
        [],
        [],
        [],
        0,
        FusionMatrix(num_classes),
    )

    func = torch.nn.Softmax(dim=1)
    logits = []
    labels_epoch = []
    prediction_epoch = []
    with torch.no_grad():
        for i, (image, image_labels, meta) in enumerate(dataLoader):
            labels_epoch.extend(image_labels.numpy())
            image = image.to(device)
            # output = model(image)
            feature = model(image, feature_flag=True)
            output = model(feature, classifier_flag=True)
            result = func(output)
            logits.extend(output)
            _, top_k = result.topk(5, 1, True, True)
            score_result = result.cpu().numpy()
            prediction_epoch.extend(score_result.argmax(axis=1))
            if not test_mode:
                fusion_matrix.update(score_result.argmax(axis=1), image_labels.numpy())
                # print(result, image_labels.numpy(), score_result.argmax(axis=1))
                #prediction_epoch.extend(score_result.argmax(axis=1))
                topk_result = top_k.cpu().tolist()
                if not "image_id" in meta:
                    meta["image_id"] = [0] * image.shape[0]
                image_ids = meta["image_id"]
                for i, image_id in enumerate(image_ids):
                    result_list.append(
                        {
                            "image_id": image_id,
                            "image_label": int(image_labels[i]),
                            "top_3": topk_result[i],
                        }
                    )
                    top1_count += [topk_result[i][0] == image_labels[i]]
                    top2_count += [image_labels[i] in topk_result[i][0:2]]
                    top3_count += [image_labels[i] in topk_result[i][0:3]]
                    index += 1
                now_acc = np.sum(top1_count) / index
                pbar.set_description("Now Top1:{:>5.2f}%".format(now_acc * 100))
            pbar.update(1)
    if not test_mode:
        top1_acc = float(np.sum(top1_count) / len(top1_count))
        top2_acc = float(np.sum(top2_count) / len(top1_count))
        top3_acc = float(np.sum(top3_count) / len(top1_count))
    target_names = ['class 0', 'class 1', 'class 2', 'class 3', 'class 4']
    catogary_map = {0: 'W', 1: 'N1', 2: 'N2', 3: 'N3', 4: 'R'}
    #submission = pd.DataFrame({"logits": logits, "prediction": prediction_epoch, "labels": labels_epoch})
    if test_mode:
        submission = pd.DataFrame({"prediction": prediction_epoch})
        submission['prediction'] = submission['prediction'].map(catogary_map)
        submission.to_excel(save_path, index=False, header=False)
    else:
        my_labels_epoch = pickle.load(open('../eval/eval1/' + 'label_F', 'rb'))
        my_labels_epoch = np.array(my_labels_epoch, dtype=np.uint8)
        submission = pd.DataFrame({"prediction": prediction_epoch, "labels": my_labels_epoch, "my_labels": labels_epoch})
        submission['prediction'] = submission['prediction'].map(catogary_map)
        submission['labels'] = submission['labels'].map(catogary_map)
        submission['my_labels'] = submission['my_labels'].map(catogary_map)
        submission.to_excel(save_path, index=False)

    #submission.to_csv(save_path, index=False)
    #submission.to_excel(save_path, index=False)
    if not test_mode:
        print(classification_report(labels_epoch, prediction_epoch, labels=[0, 1, 2, 3, 4], target_names=target_names,
                                    digits=3))
        print(
            "Top1:{:>5.2f}%  Top2:{:>5.2f}%  Top3:{:>5.2f}%".format(
                top1_acc * 100, top2_acc * 100, top3_acc * 100
            )
        )
    pbar.close()


# validLoader, epoch, model, cfg, criterion, logger, device, writer=writer
def _valid_model(dataLoader, epoch_number, model, device, **kwargs):
    model.eval()
    num_classes = dataLoader.dataset.get_num_classes()
    fusion_matrix = FusionMatrix(num_classes)

    with torch.no_grad():
        all_loss = AverageMeter()
        acc = AverageMeter()
        func = torch.nn.Softmax(dim=1)
        for i, (image, label, meta) in enumerate(dataLoader):
            image, label = image.to(device), label.to(device)

            feature = model(image, feature_flag=True)

            output = model(feature, classifier_flag=True)
            # loss = criterion(output, label)
            score_result = func(output)

            now_result = torch.argmax(score_result, 1)
            # all_loss.update(loss.data.item(), label.shape[0])
            fusion_matrix.update(now_result.cpu().numpy(), label.cpu().numpy())
            now_acc, cnt = accuracy(now_result.cpu().numpy(), label.cpu().numpy())
            acc.update(now_acc, cnt)

        pbar_str = "------- Valid: Epoch:{:>3d}  Valid_Loss:{:>5.3f}   Valid_Acc:{:>5.2f}%-------".format(
            epoch_number, all_loss.avg, acc.avg * 100
        )
        print(pbar_str)
        # logger.info(pbar_str)
    #print(acc.avg, all_loss.avg)


if __name__ == "__main__":
    args = parse_args()
    update_config(cfg, args)
    make_competation('J:/考试数据/', '../eval/',
                     ['../eval/eval1', '../eval/eval2', '../eval/eval3'])
    DIR_CV_Eval = ['../eval/eval1/', '../eval/eval2/', '../eval/eval3/']
    csv_path = 'J:/分析结果/7.xlsx'
    test_mode = True
    GPU_ID = '0'
    k = 1
    os.environ["CUDA_VISIBLE_DEVICES"] = GPU_ID
    val_label_dir = DIR_CV_Eval
    if test_mode:
        test_set = IMBALANCECASSAVA(val_label_dir, cfg, mode="mytest", transform_name=None)
    else:
        test_set = IMBALANCECASSAVA(val_label_dir, cfg, mode="valid", transform_name=None)

    num_classes = test_set.get_num_classes()
    device = torch.device("cpu" if cfg.CPU_MODE else "cuda")
    model = Network(cfg, mode="test", num_classes=num_classes)
    model_file = cfg.TEST.MODEL_FILE
    model_path = model_file
    model.load_model(model_path)
    for k, v in model.named_parameters():
        if 0 in v:
            print(k)
    if cfg.CPU_MODE:
        model = model.to(device)
    else:
        model = model.cuda()
    testLoader = DataLoader(
        test_set,
        batch_size=1,
        shuffle=False,
        num_workers=1,
        pin_memory=False,
    )
    valid_model(testLoader, model, cfg, device, num_classes, test_mode=test_mode, save_path=csv_path)
