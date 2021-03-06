# <editor-fold desc="Dependencies">
# <editor-fold desc="Dependencies">
import matplotlib
matplotlib.use('Agg')

import os
import time

import scipy


import argparse
from itertools import chain

import torch.optim as optim
from torch.autograd import Variable
from torchvision import transforms

from models.CoupledVAE import *
from trainers.coupled_vae_trainer import coupled_vae_trainer as trainer

import pickle
from utils import *
from losses import *

from image_caption.data_loader import Vocabulary
from image_caption.data_loader import get_loader
from pytorch_classification.utils import Bar, AverageMeter

# </editor-fold>

#<editor-fold desc="Arguments"
parser = argparse.ArgumentParser()
parser.add_argument('--cuda', type=str, default='true', help='Set cuda usage')
parser.add_argument('--epoch_size', type=int, default=20, help='Set epoch size')
parser.add_argument('--result_path', type=str, default='NONE',
                    help='Set the path the result images will be saved.')

parser.add_argument('--image_size', type=int, default=70,
                    help='Image size. 64 for every experiment in the paper')

parser.add_argument('--update_interval', type=int, default=3, help='')
parser.add_argument('--log_interval', type=int, default=50, help='Print loss values every log_interval iterations.')
parser.add_argument('--image_save_interval', type=int, default=1000,
                    help='Save test results every image_save_interval iterations.')
parser.add_argument('--model_save_interval', type=int, default=10000,
                    help='Save models every model_save_interval iterations.')

parser.add_argument('--model_path', type=str, default='./models/',
                    help='path for saving trained models')

parser.add_argument('--crop_size', type=int, default=64, #224
                    help='size for randomly cropping images')
parser.add_argument('--vocab_path', type=str, default='./data/vocab.pkl',
                    help='path for vocabulary wrapper')
parser.add_argument('--image_dir', type=str, default='./data/train_resized2014_70x70',
                    help='directory for resized images')
parser.add_argument('--valid_dir', type=str, default='./data/val_resized2014_70x70',
                    help='directory for resized validation set images')

parser.add_argument('--embedding_path', type=str,
                    default='./glove/',
                    help='path for pretrained embeddings')
parser.add_argument('--caption_path', type=str,
                    default='./data/annotations/captions_train2014.json',
                    help='path for train annotation json file')
parser.add_argument('--valid_caption_path', type=str,
                    default='./data/annotations/captions_val2014.json',
                    help='path for valid annotation json file')
parser.add_argument('--log_step', type=int, default=10,
                    help='step size for prining log info')
parser.add_argument('--save_step', type=int, default=1000,
                    help='step size for saving trained models')

# Model parameters
parser.add_argument('--word_embedding_size', type=int, default=300)
parser.add_argument('--hidden_size', type=int, default=1024,
                    help='dimension of lstm hidden states')
parser.add_argument('--latent_size', type=int, default=512,
                    help='dimension of latent vector z')
parser.add_argument('--num_layers', type=int, default=1,
                    help='number of layers in lstm')

parser.add_argument('--fixed_embeddings', type=str, default="true")
parser.add_argument('--num_epochs', type=int, default=20)
parser.add_argument('--batch_size', type=int, default= 32)
parser.add_argument('--num_workers', type=int, default=2)
parser.add_argument('--learning_rate', type=float, default=0.0001)

parser.add_argument('--text_criterion', type=str, default='NLLLoss')
parser.add_argument('--cm_criterion', type=str, default='Cosine')
parser.add_argument('--cm_loss_weight', type=float, default=0.8)

parser.add_argument('--common_emb_ratio', type=float, default = 0.33)
parser.add_argument('--negative_samples', type=int, default = 5)

parser.add_argument('--validate', type=str, default = "true")
parser.add_argument('--load_model', type=str, default = "NONE")

parser.add_argument('--comment', type=str, default = "test")
#</editor-fold>

def main():
    # global args
    args = parser.parse_args()

    # <editor-fold desc="Initialization">
    if args.comment == "test":
        print("WARNING: name is test!!!\n\n")


    # now = datetime.datetime.now()
    # current_date = now.strftime("%m-%d-%H-%M")

    assert args.text_criterion in ("MSE","Cosine","Hinge","NLLLoss"), 'Invalid Loss Function'
    assert args.cm_criterion in ("MSE","Cosine","Hinge"), 'Invalid Loss Function'

    assert args.common_emb_ratio <= 1.0 and args.common_emb_ratio >= 0


    #</editor-fold>

    # <editor-fold desc="Image Preprocessing">

    # Image preprocessing //ATTENTION
    # For normalization, see https://github.com/pytorch/vision#models
    transform = transforms.Compose([
        transforms.RandomCrop(args.crop_size),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        # transforms.Normalize((.5,.5,.5),
        #                      (.5, .5, .5))
        transforms.Normalize((0.485, 0.456, 0.406),
                             (0.229, 0.224, 0.225))
        ])

    #</editor-fold>

    # <editor-fold desc="Creating Embeddings">


    # Load vocabulary wrapper.
    print("Loading Vocabulary...")
    with open(args.vocab_path, 'rb') as f:
        vocab = pickle.load(f)

    # Load Embeddings
    emb_size = args.word_embedding_size
    emb_path = args.embedding_path
    if args.embedding_path[-1]=='/':
        emb_path += 'glove.6B.' + str(emb_size) + 'd.txt'

    print("Loading Embeddings...")
    emb = load_glove_embeddings(emb_path, vocab.word2idx, emb_size)

    glove_emb = nn.Embedding(emb.size(0), emb.size(1))

    # Freeze weighs
    if args.fixed_embeddings == "true":
        glove_emb.weight.requires_grad = False


    # </editor-fold>

    # <editor-fold desc="Data-Loaders">

    # Build data loader
    print("Building Data Loader For Test Set...")
    data_loader = get_loader(args.image_dir, args.caption_path, vocab,
                             transform, args.batch_size,
                             shuffle=True, num_workers=args.num_workers)

    print("Building Data Loader For Validation Set...")
    val_loader = get_loader(args.valid_dir, args.valid_caption_path, vocab,
                             transform, args.batch_size,
                             shuffle=True, num_workers=args.num_workers)

    # </editor-fold>

    # <editor-fold desc="Network Initialization">

    print("Setting up the trainer...")
    model_trainer = trainer(args, glove_emb, vocab)

    #  <\editor-fold desc="Network Initialization">


    for epoch in range(args.num_epochs):

        # <editor-fold desc = "Epoch Initialization"?

        # TRAINING TIME
        print('EPOCH ::: TRAINING ::: ' + str(epoch + 1))
        batch_time = AverageMeter()
        cm_losses = AverageMeter()
        end = time.time()

        bar = Bar('Training Net', max=len(data_loader))

        for i, (images, captions, lengths) in enumerate(data_loader):

            if i == len(data_loader)-1:
                break

            images = to_var(images)
            captions = to_var(captions)
            lengths = to_var(torch.LongTensor(lengths))            # print(captions.size())

            img_rc_loss, txt_rc_loss = model_trainer.train(images, captions, lengths, not i % args.image_save_interval)


            txt_losses.update(txt_rc_loss.data[0],args.batch_size)
            img_losses.update(img_rc_loss.data[0],args.batch_size)
            # cm_losses.update(cm_loss.data[0], args.batch_size)

            batch_time.update(time.time() - end)
            end = time.time()

            # plot progress
            bar_suffix = '({batch}/{size}) Batch: {bt:.3f}s | Total: {total:} | ETA: {eta:}'.format(
                batch=i,
                size=len(data_loader),
                bt=batch_time.avg,
                total=bar.elapsed_td,
                eta=bar.eta_td,)


            bar.next()

        # </editor-fold desc = "Logging">

        bar.finish()
        model_trainer.save_losses(epoch, img_losses.avg, txt_losses.avg)
        model_trainer.save_models(epoch)



if __name__ == "__main__":
    main()
