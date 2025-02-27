import argparse
import cv2
import torch
import torch.nn as nn
from torch.utils import data, model_zoo
import numpy as np
import pickle
from torch.autograd import Variable
import torch.optim as optim
import torch.nn.functional as F
import scipy.misc
import torch.backends.cudnn as cudnn
import sys
import os
import os.path as osp
import pickle
from packaging import version

from model.deeplab import Res_Deeplab
from model.discriminator import FCDiscriminator
from utils.loss import CrossEntropy2d, BCEWithLogitsLoss2d
from dataset.voc_dataset import VOCDataSet, VOCGTDataSet

from fd import detector

from PIL import Image

import matplotlib.pyplot as plt

import matplotlib.pyplot as plt
import random
import timeit
start = timeit.default_timer()

IMG_MEAN = np.array((104.00698793,116.66876762,122.67891434), dtype=np.float32)

MODEL = 'DeepLab'
BATCH_SIZE = int(10 / 2)
ITER_SIZE = 1
NUM_WORKERS = 4
DATA_DIRECTORY = './dataset/VOC2012'
DATA_LIST_PATH = './dataset/voc_list/train_aug.txt'
IGNORE_LABEL = 255
INPUT_SIZE = '320,320'
LEARNING_RATE = 2.5e-4 / 2
MOMENTUM = 0.9
NUM_CLASSES = 21
NUM_STEPS = 40000
POWER = 0.9
RANDOM_SEED = 1234
RESTORE_FROM = 'http://vllab1.ucmerced.edu/~whung/adv-semi-seg/resnet101COCO-41f33a49.pth'
SAVE_NUM_IMAGES = 2
SAVE_PRED_EVERY = 5000
SNAPSHOT_DIR = './snapshots_fd/'
WEIGHT_DECAY = 0.0005

LEARNING_RATE_D = 1e-4 # 0.0025
LAMBDA_ADV_PRED = 1  # ssl for labeled data

PARTIAL_DATA=0.5

SEMI_START=5000 # do not use
LAMBDA_SEMI=0.1 # do not use
MASK_T=0.2      # do not use

LAMBDA_SEMI_ADV=1   # ssl for unlabeled data
SEMI_START_ADV=0    
D_REMAIN=True       # do not use


def get_arguments():
    """Parse all the arguments provided from the CLI.

    Returns:
      A list of parsed arguments.
    """
    parser = argparse.ArgumentParser(description="DeepLab-ResNet Network")
    parser.add_argument("--model", type=str, default=MODEL,
                        help="available options : DeepLab/DRN")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                        help="Number of images sent to the network in one step.")
    parser.add_argument("--iter-size", type=int, default=ITER_SIZE,
                        help="Accumulate gradients for ITER_SIZE iterations.")
    parser.add_argument("--num-workers", type=int, default=NUM_WORKERS,
                        help="number of workers for multithread dataloading.")
    parser.add_argument("--data-dir", type=str, default=DATA_DIRECTORY,
                        help="Path to the directory containing the PASCAL VOC dataset.")
    parser.add_argument("--data-list", type=str, default=DATA_LIST_PATH,
                        help="Path to the file listing the images in the dataset.")
    parser.add_argument("--partial-data", type=float, default=PARTIAL_DATA,
                        help="The index of the label to ignore during the training.")
    parser.add_argument("--partial-id", type=str, default=None,
                        help="restore partial id list")
    parser.add_argument("--ignore-label", type=int, default=IGNORE_LABEL,
                        help="The index of the label to ignore during the training.")
    parser.add_argument("--input-size", type=str, default=INPUT_SIZE,
                        help="Comma-separated string with height and width of images.")
    parser.add_argument("--is-training", action="store_true",
                        help="Whether to updates the running means and variances during the training.")
    parser.add_argument("--learning-rate", type=float, default=LEARNING_RATE,
                        help="Base learning rate for training with polynomial decay.")
    parser.add_argument("--learning-rate-D", type=float, default=LEARNING_RATE_D,
                        help="Base learning rate for discriminator.")
    parser.add_argument("--lambda-adv-pred", type=float, default=LAMBDA_ADV_PRED,
                        help="lambda_adv for adversarial training.")
    parser.add_argument("--lambda-semi", type=float, default=LAMBDA_SEMI,
                        help="lambda_semi for adversarial training.")
    parser.add_argument("--lambda-semi-adv", type=float, default=LAMBDA_SEMI_ADV,
                        help="lambda_semi for adversarial training.")
    parser.add_argument("--mask-T", type=float, default=MASK_T,
                        help="mask T for semi adversarial training.")
    parser.add_argument("--semi-start", type=int, default=SEMI_START,
                        help="start semi learning after # iterations")
    parser.add_argument("--semi-start-adv", type=int, default=SEMI_START_ADV,
                        help="start semi learning after # iterations")
    parser.add_argument("--D-remain", type=bool, default=D_REMAIN,
                        help="Whether to train D with unlabeled data")
    parser.add_argument("--momentum", type=float, default=MOMENTUM,
                        help="Momentum component of the optimiser.")
    parser.add_argument("--not-restore-last", action="store_true",
                        help="Whether to not restore last (FC) layers.")
    parser.add_argument("--num-classes", type=int, default=NUM_CLASSES,
                        help="Number of classes to predict (including background).")
    parser.add_argument("--num-steps", type=int, default=NUM_STEPS,
                        help="Number of training steps.")
    parser.add_argument("--power", type=float, default=POWER,
                        help="Decay parameter to compute the learning rate.")
    parser.add_argument("--random-mirror", action="store_true",
                        help="Whether to randomly mirror the inputs during the training.")
    parser.add_argument("--random-scale", action="store_true",
                        help="Whether to randomly scale the inputs during the training.")
    parser.add_argument("--random-seed", type=int, default=RANDOM_SEED,
                        help="Random seed to have reproducible results.")
    parser.add_argument("--restore-from", type=str, default=RESTORE_FROM,
                        help="Where restore model parameters from.")
    parser.add_argument("--restore-from-D", type=str, default=None,
                        help="Where restore model parameters from.")
    parser.add_argument("--save-num-images", type=int, default=SAVE_NUM_IMAGES,
                        help="How many images to save.")
    parser.add_argument("--save-pred-every", type=int, default=SAVE_PRED_EVERY,
                        help="Save summaries and checkpoint every often.")
    parser.add_argument("--snapshot-dir", type=str, default=SNAPSHOT_DIR,
                        help="Where to save snapshots of the model.")
    parser.add_argument("--weight-decay", type=float, default=WEIGHT_DECAY,
                        help="Regularisation parameter for L2-loss.")
    parser.add_argument("--gpu", type=int, default=0,
                        help="choose gpu device.")
    parser.add_argument('--save-dir', type=str, default='results_fd')

    return parser.parse_args()

args = get_arguments()

def loss_calc(pred, label, gpu):
    """
    This function returns cross entropy loss for semantic segmentation
    """
    # out shape batch_size x channels x h x w -> batch_size x channels x h x w
    # label shape h x w x 1 x batch_size  -> batch_size x 1 x h x w
    label = Variable(label.long()).cuda(gpu)
    criterion = CrossEntropy2d().cuda(gpu)

    return criterion(pred, label)


def lr_poly(base_lr, iter, max_iter, power):
    return base_lr*((1-float(iter)/max_iter)**(power))


def adjust_learning_rate(optimizer, i_iter):
    lr = lr_poly(args.learning_rate, i_iter, args.num_steps, args.power)
    optimizer.param_groups[0]['lr'] = lr
    if len(optimizer.param_groups) > 1 :
        optimizer.param_groups[1]['lr'] = lr * 10

def adjust_learning_rate_D(optimizer, i_iter):
    lr = lr_poly(args.learning_rate_D, i_iter, args.num_steps, args.power)
    optimizer.param_groups[0]['lr'] = lr
    if len(optimizer.param_groups) > 1 :
        optimizer.param_groups[1]['lr'] = lr * 10

def one_hot(label):
    label = label.numpy()
    one_hot = np.zeros((label.shape[0], args.num_classes, label.shape[1], label.shape[2]), dtype=label.dtype)
    for i in range(args.num_classes):
        one_hot[:,i,...] = (label==i)
    #handle ignore labels
    return torch.FloatTensor(one_hot)

def make_D_label(label, ignore_mask):
    ignore_mask = np.expand_dims(ignore_mask, axis=1)
    D_label = np.ones(ignore_mask.shape)*label
    D_label[ignore_mask] = 255
    D_label = Variable(torch.FloatTensor(D_label)).cuda(args.gpu)

    return D_label


def main():
    # prepare
    h, w = map(int, args.input_size.split(','))
    input_size = (h, w)

    cudnn.enabled = True
    gpu = args.gpu

    if not os.path.exists(args.save_dir):
        os.makedirs(args.save_dir)

    # create network
    model = Res_Deeplab(num_classes=args.num_classes)

    # load pretrained parameters
    if args.restore_from[:4] == 'http' :
        saved_state_dict = model_zoo.load_url(args.restore_from)
    else:
        saved_state_dict = torch.load(args.restore_from)

    # only copy the params that exist in current model (caffe-like)
    new_params = model.state_dict().copy()
    for name, param in new_params.items():
        if name in saved_state_dict and param.size() == saved_state_dict[name].size():
            new_params[name].copy_(saved_state_dict[name])
            print('copy {}'.format(name))
    model.load_state_dict(new_params)


    model.train()
    model.cuda(args.gpu)

    cudnn.benchmark = True

    # init D
    model_D = detector.FlawDetector(in_channels=24)
    # model_D = FCDiscriminator(num_classes=args.num_classes)
    if args.restore_from_D is not None:
        model_D.load_state_dict(torch.load(args.restore_from_D))
    model_D.train()
    model_D.cuda(args.gpu)


    if not os.path.exists(args.snapshot_dir):
        os.makedirs(args.snapshot_dir)


    train_dataset = VOCDataSet(args.data_dir, args.data_list, crop_size=input_size,
                    scale=args.random_scale, mirror=args.random_mirror, mean=IMG_MEAN)

    train_dataset_size = len(train_dataset)

    train_gt_dataset = VOCGTDataSet(args.data_dir, args.data_list, crop_size=input_size,
                       scale=args.random_scale, mirror=args.random_mirror, mean=IMG_MEAN)

    if args.partial_data is None:
        trainloader = data.DataLoader(train_dataset,
                        batch_size=args.batch_size, shuffle=True, num_workers=5, pin_memory=True)

        trainloader_gt = data.DataLoader(train_gt_dataset,
                        batch_size=args.batch_size, shuffle=True, num_workers=5, pin_memory=True)
    else:
        #sample partial data
        partial_size = int(args.partial_data * train_dataset_size)

        if args.partial_id is not None:
            train_ids = pickle.load(open(args.partial_id))
            print('loading train ids from {}'.format(args.partial_id))
        else:
            train_ids = [_ for _ in range(0, train_dataset_size)]
            np.random.shuffle(train_ids)

        pickle.dump(train_ids, open(osp.join(args.snapshot_dir, 'train_id.pkl'), 'wb'))

        train_sampler = data.sampler.SubsetRandomSampler(train_ids[:partial_size])
        train_remain_sampler = data.sampler.SubsetRandomSampler(train_ids[partial_size:])
        train_gt_sampler = data.sampler.SubsetRandomSampler(train_ids[:partial_size])

        trainloader = data.DataLoader(train_dataset,
                        batch_size=args.batch_size, sampler=train_sampler, num_workers=3, pin_memory=True)
        trainloader_remain = data.DataLoader(train_dataset,
                        batch_size=args.batch_size, sampler=train_remain_sampler, num_workers=3, pin_memory=True)
        trainloader_gt = data.DataLoader(train_gt_dataset,
                        batch_size=args.batch_size, sampler=train_gt_sampler, num_workers=3, pin_memory=True)

        trainloader_remain_iter = enumerate(trainloader_remain)


    trainloader_iter = enumerate(trainloader)
    trainloader_gt_iter = enumerate(trainloader_gt)


    # implement model.optim_parameters(args) to handle different models' lr setting

    # optimizer for segmentation network
    optimizer = optim.SGD(model.optim_parameters(args),
                lr=args.learning_rate, momentum=args.momentum,weight_decay=args.weight_decay)
    optimizer.zero_grad()

    # optimizer for discriminator network
    optimizer_D = optim.Adam(model_D.parameters(), lr=args.learning_rate_D, betas=(0.9,0.99))
    optimizer_D.zero_grad()

    # loss/ bilinear upsampling
    minimum_loss = detector.MinimumCriterion()
    detector_loss = detector.FlawDetectorCriterion()

    # bce_loss = BCEWithLogitsLoss2d()
    interp = nn.Upsample(size=(input_size[1], input_size[0]), mode='bilinear')

    if version.parse(torch.__version__) >= version.parse('0.4.0'):
        interp = nn.Upsample(size=(input_size[1], input_size[0]), mode='bilinear', align_corners=True)
    else:
        interp = nn.Upsample(size=(input_size[1], input_size[0]), mode='bilinear')


    # labels for adversarial training
    pred_label = 0
    gt_label = 1


    for i_iter in range(args.num_steps):
        
        if i_iter > 0 and i_iter % 1000 == 0:
            val(model, args.gpu)
            model.train()

        loss_seg_value = 0
        loss_adv_pred_value = 0
        loss_D_value = 0
        loss_semi_value = 0
        loss_semi_adv_value = 0

        optimizer.zero_grad()
        adjust_learning_rate(optimizer, i_iter)
        optimizer_D.zero_grad()
        adjust_learning_rate_D(optimizer_D, i_iter)

        for sub_i in range(args.iter_size):

            # train G

            # don't accumulate grads in D
            for param in model_D.parameters():
                param.requires_grad = False

            # do semi first
            if (args.lambda_semi > 0 or args.lambda_semi_adv > 0 ) and i_iter >= args.semi_start_adv :
                try:
                    _, batch = trainloader_remain_iter.__next__()
                except:
                    trainloader_remain_iter = enumerate(trainloader_remain)
                    _, batch = trainloader_remain_iter.__next__()

                # only access to img
                images, _, _, _ = batch
                images = Variable(images).cuda(args.gpu)


                pred = interp(model(images))
                pred_remain = pred.detach()

                D_out = model_D(images, pred)

                ignore_mask_remain = np.zeros(D_out.shape).astype(np.bool)
                loss_semi_adv = args.lambda_semi_adv * minimum_loss(D_out)  # ke: SSL loss for unlabeled data
                loss_semi_adv = loss_semi_adv

                #loss_semi_adv.backward()
                loss_semi_adv_value += loss_semi_adv.data.cpu().numpy() / args.iter_size

                loss_semi_adv.backward()
                loss_semi_value = 0

            else:
                loss_semi = None
                loss_semi_adv = None

            # train with source (labeled data)

            try:
                _, batch = trainloader_iter.__next__()
            except:
                trainloader_iter = enumerate(trainloader)
                _, batch = trainloader_iter.__next__()

            images, labels, _, _ = batch
            images = Variable(images).cuda(args.gpu)
            ignore_mask = (labels.numpy() == 255)
            pred = interp(model(images))

            loss_seg = loss_calc(pred, labels, args.gpu)

            D_out = interp(model_D(images, pred))
           
            loss_adv_pred = args.lambda_adv_pred * minimum_loss(D_out)   # ke: SSL loss for labeled data

            loss = loss_seg + loss_adv_pred

            # proper normalization
            loss = loss/args.iter_size
            loss.backward()
            loss_seg_value += loss_seg.data.cpu().numpy()/args.iter_size
            loss_adv_pred_value += loss_adv_pred.data.cpu().numpy()/args.iter_size

            # train D

            # bring back requires_grad
            for param in model_D.parameters():
                param.requires_grad = True

            # train with pred from labeled data
            pred = pred.detach()

            D_out = interp(model_D(images, pred))

            detect_gt = detector.generate_flaw_detector_gt(
                pred, labels.view(labels.shape[0], 1, labels.shape[1], labels.shape[2]).cuda(args.gpu),
                NUM_CLASSES, IGNORE_LABEL)
            loss_D = detector_loss(D_out, detect_gt)

            loss_D = loss_D/args.iter_size/2
            loss_D.backward()
            loss_D_value += loss_D.data.cpu().numpy()


            # # train with gt
            # # get gt labels
            # try:
            #     _, batch = trainloader_gt_iter.__next__()
            # except:
            #     trainloader_gt_iter = enumerate(trainloader_gt)
            #     _, batch = trainloader_gt_iter.__next__()

            # _, labels_gt, _, _ = batch
            # D_gt_v = Variable(one_hot(labels_gt)).cuda(args.gpu)
            # ignore_mask_gt = (labels_gt.numpy() == 255)

            # D_out = interp(model_D(D_gt_v))
            # loss_D = bce_loss(D_out, make_D_label(gt_label, ignore_mask_gt))
            # loss_D = loss_D/args.iter_size/2
            # loss_D.backward()
            # loss_D_value += loss_D.data.cpu().numpy()


        optimizer.step()
        optimizer_D.step()

        print('exp = {}'.format(args.snapshot_dir))
        print('iter = {0:8d}/{1:8d}, loss_seg = {2:.6f}, loss_adv_l = {3:.6f}, loss_D = {4:.6f}, loss_semi = {5:.6f}, loss_adv_u = {6:.6f}'.format(i_iter, args.num_steps, loss_seg_value, loss_adv_pred_value, loss_D_value, loss_semi_value, loss_semi_adv_value))

        if i_iter >= args.num_steps-1:
            torch.save(model.state_dict(),osp.join(args.snapshot_dir, 'VOC_'+str(args.num_steps)+'.pth'))
            torch.save(model_D.state_dict(),osp.join(args.snapshot_dir, 'VOC_'+str(args.num_steps)+'_D.pth'))
            break

        if i_iter % args.save_pred_every == 0 and i_iter!=0:
            torch.save(model.state_dict(),osp.join(args.snapshot_dir, 'VOC_'+str(i_iter)+'.pth'))
            torch.save(model_D.state_dict(),osp.join(args.snapshot_dir, 'VOC_'+str(i_iter)+'_D.pth'))

    end = timeit.default_timer()


def val(model, gpu):
    model.eval()

    testloader = data.DataLoader(
        VOCDataSet('./dataset/VOC2012', 
                   './dataset/voc_list/val.txt',
                   crop_size=(505, 505), 
                   mean=np.array((104.00698793,116.66876762,122.67891434), dtype=np.float32),
                   scale=False, mirror=False),
                   batch_size=1, shuffle=False, pin_memory=True)

    if version.parse(torch.__version__) >= version.parse('0.4.0'):
        interp = nn.Upsample(size=(505, 505), mode='bilinear', align_corners=True)
    else:
        interp = nn.Upsample(size=(505, 505), mode='bilinear')
    data_list = []
    
    from evaluate_voc import VOCColorize, get_iou
    colorize = VOCColorize()

    for index, batch in enumerate(testloader):
        if index % 100 == 0:
            print('%d processd'%(index))
        image, label, size, name = batch
        size = size[0].numpy()
        output = model(Variable(image, volatile=True).cuda(gpu))
        output = interp(output).cpu().data[0].numpy()

        output = output[:,:size[0],:size[1]]
        gt = np.asarray(label[0].numpy()[:size[0],:size[1]], dtype=np.int)

        output = output.transpose(1,2,0)
        output = np.asarray(np.argmax(output, axis=2), dtype=np.int)

        filename = os.path.join(args.save_dir, '{}.png'.format(name[0]))
        color_file = Image.fromarray(colorize(output).transpose(1, 2, 0), 'RGB')
        color_file.save(filename)

        # show_all(gt, output)
        data_list.append([gt.flatten(), output.flatten()])

    filename = os.path.join(args.save_dir, 'result.txt')
    get_iou(data_list, args.num_classes, filename)


if __name__ == '__main__':
    main()
