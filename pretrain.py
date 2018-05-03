import os
import argparse
from itertools import chain

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.autograd import Variable
from torch.nn.utils.rnn import pack_padded_sequence
from torchvision import transforms
from torchtext import vocab
from model import *
import pickle

from utils import *

from image_caption.build_vocab import Vocabulary
from image_caption.data_loader import get_loader



from progressbar import ETA, Bar, Percentage, ProgressBar

parser = argparse.ArgumentParser()
parser.add_argument('--cuda', type=str, default='true', help='Set cuda usage')
parser.add_argument('--epoch_size', type=int, default=5000, help='Set epoch size')
parser.add_argument('--result_path', type=str, default='./results/',
                    help='Set the path the result images will be saved.')

parser.add_argument('--image_size', type=int, default=256, help='Image size. 64 for every experiment in the paper')

parser.add_argument('--update_interval', type=int, default=3, help='')
parser.add_argument('--log_interval', type=int, default=50, help='Print loss values every log_interval iterations.')
parser.add_argument('--image_save_interval', type=int, default=1000,
                    help='Save test results every image_save_interval iterations.')
parser.add_argument('--model_save_interval', type=int, default=10000,
                    help='Save models every model_save_interval iterations.')

parser.add_argument('--model_path', type=str, default='./models/',
                    help='path for saving trained models')

parser.add_argument('--crop_size', type=int, default=224,
                    help='size for randomly cropping images')
parser.add_argument('--vocab_path', type=str, default='./data/vocab.pkl',
                    help='path for vocabulary wrapper')
parser.add_argument('--image_dir', type=str, default='./data/resized2014',
                    help='directory for resized images')

parser.add_argument('--embedding_path', type=str,
                    default='./glove/',
                    help='path for pretrained embeddings')
parser.add_argument('--caption_path', type=str,
                    default='./data/annotations/captions_train2014.json',
                    help='path for train annotation json file')
parser.add_argument('--log_step', type=int, default=10,
                    help='step size for prining log info')
parser.add_argument('--save_step', type=int, default=1000,
                    help='step size for saving trained models')


# Model parameters
parser.add_argument('--embedding_size', type=int, default=100)
parser.add_argument('--hidden_size', type=int, default=300,
                    help='dimension of lstm hidden states')
parser.add_argument('--num_layers', type=int, default=1,
                    help='number of layers in lstm')

parser.add_argument('--extra_layers', type=str, default='true')
parser.add_argument('--fixed_embeddings', type=str, default="true")
parser.add_argument('--num_epochs', type=int, default=5)
parser.add_argument('--batch_size', type=int, default=64)
parser.add_argument('--num_workers', type=int, default=2)
parser.add_argument('--learning_rate', type=float, default=0.001)

def main():
    # global args
    args = parser.parse_args()

    cuda = args.cuda
    if cuda == 'true':
        cuda = True
    else:
        cuda = False

    # Image preprocessing
    # For normalization, see https://github.com/pytorch/vision#models
    transform = transforms.Compose([
        transforms.RandomCrop(args.crop_size),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize((0.485, 0.456, 0.406),
                             (0.229, 0.224, 0.225))])

    result_path = args.result_path
    model_path = args.model_path

    if not os.path.exists(result_path):
        os.makedirs(result_path)
    if not os.path.exists(model_path):
        os.makedirs(model_path)


    # Load vocabulary wrapper.
    print("Loading Vocabulary...")
    with open(args.vocab_path, 'rb') as f:
        vocab = pickle.load(f)

    # Load Embeddings
    emb_size = args.embedding_size
    emb_path = args.embedding_path
    if args.embedding_path[-1]=='/':
        emb_path += 'glove.6B.' + str(emb_size) + 'd.txt'

    print("Loading Embeddings...")
    emb = load_glove_embeddings(emb_path, vocab.word2idx, emb_size)

    glove_emb = nn.Embedding(emb.size(0), emb.size(1))
    glove_emb.weight = nn.Parameter(emb)

    # Freeze weighs
    if args.fixed_embeddings == "true":
        glove_emb.weight.requires_grad = False

    # Build data loader
    print("Building Data Loader...")
    data_loader = get_loader(args.image_dir, args.caption_path, vocab,
                             transform, args.batch_size,
                             shuffle=True, num_workers=args.num_workers)

    print("Setting up the Networks...")
    #     generator_A = Generator()
    encoder_Txt = TextEncoder(glove_emb, hidden_size=args.hidden_size)
    # decoder_Txt = TextDecoder(encoder_Txt, glove_emb)
    decoder_Txt = DecoderRNN(glove_emb, hidden_size=args.hidden_size)



    #     generator_B = Generator()
    encoder_Img = ImageEncoder(feature_dimension= args.hidden_size, extra_layers= (args.extra_layers == 'true'))
    decoder_Img = ImageDecoder(feature_dimension= args.hidden_size, extra_layers= (args.extra_layers == 'true'))

    if cuda:
        # test_I = test_I.cuda()
        # test_T = test_T.cuda()

        #          generator_A = generator_A.cuda()
        #        generator_A = generator_A.cuda()

        encoder_Txt = encoder_Txt.cuda()
        decoder_Img = decoder_Img.cuda()

        #         generator_B = generator_B.cuda()
        encoder_Img = encoder_Img.cuda()
        decoder_Txt = decoder_Txt.cuda()


    # Losses and Optimizers
    print("Setting up the Objective Functions...")
    img_criterion = nn.MSELoss()
    txt_criterion = nn.CrossEntropyLoss()
    cm_criterion = nn.MSELoss()

    #     gen_params = chain(generator_A.parameters(), generator_B.parameters())
    print("Setting up the Optimizers...")
    # img_params = chain(decoder_Img.parameters(), encoder_Img.parameters())
    # txt_params = chain(decoder_Txt.parameters(), encoder_Txt.parameters())

    # ATTENTION: Check betas and weight decay
    # ATTENTION: Check why valid_params fails on image networks with out of memory error
    img_enc_optim = optim.Adam(encoder_Img.parameters(), lr=args.learning_rate)#betas=(0.5, 0.999), weight_decay=0.00001)
    img_dec_optim = optim.Adam(decoder_Img.parameters(), lr=args.learning_rate)#betas=(0.5,0.999), weight_decay=0.00001)
    txt_enc_optim = optim.Adam(valid_params(encoder_Txt.parameters()), lr=args.learning_rate)#betas=(0.5,0.999), weight_decay=0.00001)
    txt_dec_optim = optim.Adam(valid_params(decoder_Txt.parameters()), lr=args.learning_rate)#betas=(0.5,0.999), weight_decay=0.00001)


    total_step = len(data_loader)
    for epoch in range(args.num_epochs):
        #         We don't want our data to be shuffled
        #         data_style_A, data_style_B = shuffle_data( data_style_A, data_style_B)

        widgets = ['epoch #%d|' % epoch, Percentage(), Bar(), ETA()]
        pbar = ProgressBar(maxval=total_step, widgets=widgets)
        pbar.start()

        for i, (images, captions, lengths) in enumerate(data_loader):
            pbar.update(i)

            # Set mini-batch dataset //ATTENTION CHECK TYPES DISCOGAN
            images = to_var(images, volatile=True)
            # captions = to_var(captions)
            targets = pack_padded_sequence(captions, lengths, batch_first=True)[0]

            # Set training mode
            encoder_Txt.train()
            decoder_Txt.train()

            #Forward, Backward and Optimize
            img_dec_optim.zero_grad()
            img_enc_optim.zero_grad()

            txt_dec_optim.zero_grad()
            txt_enc_optim.zero_grad()


            Iz = encoder_Img(images)
            IzI = decoder_Img(Iz)

            img_rc_loss = img_criterion(IzI,images)

            src_seqs, src_lens = pad_sequences(captions)

            if cuda:
                src_seqs = src_seqs.cuda()

            Tz = encoder_Txt(src_seqs, src_lens)
            TzT = decoder_Txt(Tz, captions, lengths)


            txt_rc_loss = txt_criterion(TzT,targets)
            cm_loss = cm_criterion(Iz,Tz)


            rate = 0.9
            img_loss = img_rc_loss * (1 - rate) + cm_loss * rate
            txt_loss = txt_rc_loss * (1 - rate) + cm_loss * rate

            # Half of the times we update one pipeline the others the other one
            if i % 2 == 0:
                img_loss.backward()
                img_enc_optim.step()
                img_dec_optim.step()
            else:
                txt_loss.backward()
                txt_enc_optim.step()
                txt_dec_optim.step()

            if i % args.log_interval == 0:
                print("---------------------")
                print("Img Loss: " + as_np(img_rc_loss.mean()))
                print("Txt Loss: " + as_np(img_rc_loss.mean()))
                print("Cross-Modal Loss: " + as_np(cm_loss.mean()))

            # Save the models
            if (i+1) % args.save_step == 0:
                torch.save(decoder_Img.state_dict(),
                           os.path.join(args.model_path,
                                        'decoder-img-%d-%d.pkl' %(epoch+1, i+1)))
                torch.save(encoder_Img.state_dict(),
                           os.path.join(args.model_path,
                                        'encoder-img-%d-%d.pkl' %(epoch+1, i+1)))
                torch.save(decoder_Txt.state_dict(),
                           os.path.join(args.model_path,
                                        'decoder-txt-%d-%d.pkl' %(epoch+1, i+1)))
                torch.save(encoder_Txt.state_dict(),
                           os.path.join(args.model_path,
                                        'encoder-txt-%d-%d.pkl' %(epoch+1, i+1)))


if __name__ == "__main__":
    main()
