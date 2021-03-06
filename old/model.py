import torch
import torch.nn as nn
import torch.nn.functional as F

from torch.nn.utils.rnn import pack_padded_sequence

from torch.autograd import Variable
# import ipdb

from onmt import Models
import numpy as np

kernel_sizes = [4,3,3]
strides = [2,2,1]
paddings=[0,0,1]

latent_dim = 300

class TextEncoderOld(nn.Module):
    def __init__(
            self,
            embedding,
            hidden_size = latent_dim,
            num_layers = 1,
            bidirectional = True,
            bridge = False
            ):
        super(TextEncoderOld, self).__init__()

        self.hidden_dim = hidden_size
        self.num_layers = num_layers

        self.embedding = embedding
        self.enc_layers = self.embedding.embedding_size

        rnn_type = "GRU"
        brnn = bidirectional

        rnn_size = self.hidden_dim
        dropout = 0.3
        self.encoder = Models.RNNEncoder(rnn_type, brnn, num_layers,
                          rnn_size, dropout, embedding,
                          bridge)

    def forward(self, src, lengths):

        # tgt = tgt[:-1]  # exclude last target from inputs
        # src = src.transpose(0,1).unsqueeze(2)
        # lengths = torch.LongTensor(lengths)
        # print(len(lengths))
        return self.encoder(src, lengths)

class TextDecoderOld(nn.Module):
    def __init__(
            self,
            embeddings,
            num_layers = 1,
            rnn_type="GRU",
            hidden_size = latent_dim,
            bidirectional = False
            ):
        super(TextDecoderOld,self).__init__()

        global_attention = "general"
        coverage_attn = False
        context_gate = None
        copy_attn = False
        reuse_copy_attn = False
        dropout = 0.3


        self.decoder = Models.StdRNNDecoder(rnn_type, bidirectional,
                             num_layers, hidden_size,
                             global_attention,
                             coverage_attn,
                             context_gate,
                             copy_attn,
                             dropout,
                             embeddings,
                             reuse_copy_attn)

        def forward(self, *input, **kargs):
            return self.decoder(*input, **kargs)

#source: https://github.com/howardyclo/pytorch-seq2seq-example/blob/master/seq2seq.ipynb


class DecoderRNN(nn.Module):
    def __init__(self, embeds, hidden_size = latent_dim, num_layers=1):
        """Set the hyper-parameters and build the layers."""
        super(DecoderRNN, self).__init__()
        self.embed = embeds
        self.embed_size = self.embed.embedding_dim
        self.lstm = nn.LSTM(self.embed_size, hidden_size, num_layers, batch_first=True)
        self.linear = nn.Linear(hidden_size, self.embed_size)
        self.init_weights()

    def init_weights(self):
        """Initialize weights."""
        # self.embed.weight.data.uniform_(-0.1, 0.1)
        self.linear.weight.data.uniform_(-0.1, 0.1)
        self.linear.bias.data.fill_(0)

    def forward(self, features, captions, lengths):
        """Decode image feature vectors and generates captions."""
        embeddings = self.embed(captions)
        # print(str(embeddings).encode('utf-8'))
        features = features.transpose(0,1)
        print(features.size())
        print(embeddings.size())
        embeddings = torch.cat((features, embeddings), 1)
        packed = pack_padded_sequence(embeddings, lengths, batch_first=True)
        hiddens, _ = self.lstm(packed)
        outputs = self.linear(hiddens[0])
        return outputs

    def sample(self, features, states=None):
        """Samples captions for given image features (Greedy search)."""
        sampled_ids = []
        inputs = features.unsqueeze(1)
        for i in range(20):                                      # maximum sampling length
            hiddens, states = self.lstm(inputs, states)          # (batch_size, 1, hidden_size),
            outputs = self.linear(hiddens.squeeze(1))            # (batch_size, vocab_size)
            predicted = outputs.max(1)[1]
            sampled_ids.append(predicted)
            inputs = self.embed(predicted)
            inputs = inputs.unsqueeze(1)                         # (batch_size, 1, embed_size)
        sampled_ids = torch.cat(sampled_ids, 1)                  # (batch_size, 20)
        return sampled_ids.squeeze()

class TextDecoder(nn.Module):
        def __init__(self, encoder, embedding=None, bias=True, tie_embeddings=True, dropout=0.3):
            """ General attention in `Effective Approaches to Attention-based Neural Machine Translation`
                Ref: https://arxiv.org/abs/1508.04025

                Removed Attention

                Share input and output embeddings:
                Ref:
                    - "Using the Output Embedding to Improve Language Models" (Press & Wolf 2016)
                       https://arxiv.org/abs/1608.05859
                    - "Tying Word Vectors and Word Classifiers: A Loss Framework for Language Modeling" (Inan et al. 2016)
                       https://arxiv.org/abs/1611.01462
            """
            super(TextDecoder, self).__init__()

            self.hidden_size = encoder.hidden_size * encoder.num_directions
            self.num_layers = encoder.num_layers
            self.dropout = dropout
            self.embedding = embedding
            self.tie_embeddings = tie_embeddings

            self.vocab_size = self.embedding.num_embeddings
            self.word_vec_size = self.embedding.embedding_dim

            self.rnn_type = encoder.rnn_type
            self.rnn = getattr(nn, self.rnn_type)(
                input_size=self.word_vec_size,
                hidden_size=self.hidden_size,
                num_layers=self.num_layers,
                dropout=self.dropout)

            if self.tie_embeddings:
                self.W_proj = nn.Linear(self.hidden_size, self.word_vec_size, bias=bias)
                self.W_s = nn.Linear(self.word_vec_size, self.vocab_size, bias=bias)
                self.W_s.weight = self.embedding.weight
            else:
                self.W_s = nn.Linear(self.hidden_size, self.vocab_size, bias=bias)

        def forward(self, input_seq, decoder_hidden, encoder_outputs, src_lens):
            """ Args:
                - input_seq      : (batch_size)
                - decoder_hidden : (t=0) last encoder hidden state (num_layers * num_directions, batch_size, hidden_size)
                                   (t>0) previous decoder hidden state (num_layers, batch_size, hidden_size)
                - encoder_outputs: (max_src_len, batch_size, hidden_size * num_directions)

                Returns:
                - output           : (batch_size, vocab_size)
                - decoder_hidden   : (num_layers, batch_size, hidden_size)
                - attention_weights: (batch_size, max_src_len)
            """
            # (batch_size) => (seq_len=1, batch_size)
            input_seq = input_seq.unsqueeze(0)

            # (seq_len=1, batch_size) => (seq_len=1, batch_size, word_vec_size)
            emb = self.embedding(input_seq)

            # rnn returns:
            # - decoder_output: (seq_len=1, batch_size, hidden_size)
            # - decoder_hidden: (num_layers, batch_size, hidden_size)
            decoder_output, decoder_hidden = self.rnn(emb, decoder_hidden)

            # (seq_len=1, batch_size, hidden_size) => (batch_size, seq_len=1, hidden_size)
            decoder_output = decoder_output.transpose(0, 1)

            concat_output = decoder_output

            # If input and output embeddings are tied,
            # project `decoder_hidden_size` to `word_vec_size`.
            if self.tie_embeddings:
                output = self.W_s(self.W_proj(concat_output))
            else:
                # (batch_size, seq_len=1, decoder_hidden_size) => (batch_size, seq_len=1, vocab_size)
                output = self.W_s(concat_output)

                # Prepare returns:
            # (batch_size, seq_len=1, vocab_size) => (batch_size, vocab_size)
            output = output.squeeze(1)

            del src_lens

            return output, decoder_hidden


class ImageEncoder(nn.Module):
    def __init__(
            self,
            img_dimension=256,
            feature_dimension = 300
            ):

        super(ImageEncoder, self).__init__()

        self.feat_dim = feature_dimension

        if img_dimension == 64 :
            self.main = nn.Sequential(
                nn.Conv2d(3, img_dimension, 4, 2, 1, bias=False),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(img_dimension, img_dimension * 2, 4, 2, 1, bias=False),
                nn.BatchNorm2d(img_dimension * 2),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(img_dimension * 2, img_dimension * 4, 4, 2, 1, bias=False),
                nn.BatchNorm2d(img_dimension * 4),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(img_dimension * 4, img_dimension * 8, 4, 2, 1, bias=False),
                nn.BatchNorm2d(img_dimension * 8),
                nn.LeakyReLU(0.2, inplace=True),
                # nn.Conv2d(img_dimension * 8, img_dimension * 8, 4, 2, 1, bias=False),
                # nn.BatchNorm2d(img_dimension * 8),
                # nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(img_dimension * 8, feature_dimension, 4, 1, 0, bias=False),
                nn.BatchNorm2d(feature_dimension),
                nn.LeakyReLU(0.2, inplace=True),
            )
        else:
            self.main = nn.Sequential(
                nn.Conv2d(3, img_dimension, 4, 2, 1, bias=False),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(img_dimension, img_dimension * 2, 4, 2, 1, bias=False),
                nn.BatchNorm2d(img_dimension * 2),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(img_dimension * 2, img_dimension * 4, 4, 2, 1, bias=False),
                nn.BatchNorm2d(img_dimension * 4),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(img_dimension * 4, img_dimension * 8, 4, 2, 1, bias=False),
                nn.BatchNorm2d(img_dimension * 8),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(img_dimension * 8, img_dimension * 8, 4, 2, 1, bias=False),
                nn.BatchNorm2d(img_dimension * 8),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(img_dimension * 8, feature_dimension, 4, 1, 0, bias=False),
                nn.BatchNorm2d(feature_dimension),
                nn.LeakyReLU(0.2, inplace=True),
            )

    def forward(self, input):
        x = self.main(input)
        # x_cap = x.view(-1, self.feat_dim * 4 * 4)
        # x_cap = self.fc(x_cap)
        return x, x.view(-1, self.feat_dim)


class ImageDecoder(nn.Module):
    def __init__(
            self,
            img_dimension=256,
            feature_dimension =300
            ):

        super(ImageDecoder, self).__init__()

        if img_dimension == 64:
            self.main = nn.Sequential(
                nn.ConvTranspose2d(feature_dimension, img_dimension * 8, 4, 1, 0, bias=False),
                nn.BatchNorm2d(img_dimension * 8),
                nn.ReLU(True),
                # nn.ConvTranspose2d(img_dimension*8, img_dimension * 8, 4, 2, 1, bias=False),
                # nn.BatchNorm2d(img_dimension * 8),
                # nn.ReLU(True),
                nn.ConvTranspose2d(img_dimension * 8, img_dimension * 4, 4, 2, 1, bias=False),
                nn.BatchNorm2d(img_dimension * 4),
                nn.ReLU(True),
                nn.ConvTranspose2d(img_dimension * 4, img_dimension * 2, 4, 2, 1, bias=False),
                nn.BatchNorm2d(img_dimension * 2),
                nn.ReLU(True),
                nn.ConvTranspose2d(img_dimension * 2,     img_dimension, 4, 2, 1, bias=False),
                nn.BatchNorm2d(img_dimension),
                nn.ReLU(True),
                nn.ConvTranspose2d(img_dimension,      3, 4, 2, 1, bias=False),
                # nn.Sigmoid()
            )
        else:
            self.main = nn.Sequential(
                nn.ConvTranspose2d(feature_dimension, img_dimension * 8, 4, 1, 0, bias=False),
                nn.BatchNorm2d(img_dimension * 8),
                nn.ReLU(True),
                nn.ConvTranspose2d(img_dimension*8, img_dimension * 8, 4, 2, 1, bias=False),
                nn.BatchNorm2d(img_dimension * 8),
                nn.ReLU(True),
                nn.ConvTranspose2d(img_dimension * 8, img_dimension * 4, 4, 2, 1, bias=False),
                nn.BatchNorm2d(img_dimension * 4),
                nn.ReLU(True),
                nn.ConvTranspose2d(img_dimension * 4, img_dimension * 2, 4, 2, 1, bias=False),
                nn.BatchNorm2d(img_dimension * 2),
                nn.ReLU(True),
                nn.ConvTranspose2d(img_dimension * 2,     img_dimension, 4, 2, 1, bias=False),
                nn.BatchNorm2d(img_dimension),
                nn.ReLU(True),
                nn.ConvTranspose2d(img_dimension,      3, 4, 2, 1, bias=False),
                # nn.Sigmoid()
            )

    def forward(self, input):
        return self.main( input )

class ImageVariationalEncoder(nn.Module):
    def __init__(
            self,
            img_dimension=256,
            feature_dimension = 300
            ):

        super(ImageVariationalEncoder, self).__init__()

        self.feat_dim = feature_dimension

        self.main = nn.Sequential(
            nn.Conv2d(3, img_dimension, 4, 2, 1, bias=False),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Conv2d(img_dimension, img_dimension * 2, 4, 2, 1, bias=False),
            nn.BatchNorm2d(img_dimension * 2),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Conv2d(img_dimension * 2, img_dimension * 4, 4, 2, 1, bias=False),
            nn.BatchNorm2d(img_dimension * 4),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Conv2d(img_dimension * 4, img_dimension * 8, 4, 2, 1, bias=False),
            nn.BatchNorm2d(img_dimension * 8),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Conv2d(img_dimension * 8, img_dimension * 8, 4, 2, 1, bias=False),
            nn.BatchNorm2d(img_dimension * 8),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Conv2d(img_dimension * 8, 1024, 4, 1, 0, bias=False),
            nn.BatchNorm2d(feature_dimension), # Should it be here?
            nn.LeakyReLU(0.2, inplace=True),
            # nn.Sigmoid()
        )

        self.fc1 = nn.Linear(1024, 512)
        self.mu = nn.Linear(512, feature_dimension)
        self.std = nn.Linear(512, feature_dimension)

    def forward(self, input):
        x = self.main(input)
        h = self.fc1(x.view(-1, 1024))

        # x_cap = self.fc(x_cap)
        return self.mu(h), self.std(h)


class ImageVariationalDecoder(nn.Module):
    def __init__(
            self,
            img_dimension=256,
            feature_dimension =300
            ):

        super(ImageVariationalDecoder, self).__init__()

        self.main = nn.Sequential(
            nn.ConvTranspose2d(feature_dimension, img_dimension * 8, 4, 1, 0, bias=False),
            nn.BatchNorm2d(img_dimension * 8),
            nn.ReLU(True),
            nn.ConvTranspose2d(img_dimension*8, img_dimension * 8, 4, 2, 1, bias=False),
            nn.BatchNorm2d(img_dimension * 8),
            nn.ReLU(True),
            nn.ConvTranspose2d(img_dimension * 8, img_dimension * 4, 4, 2, 1, bias=False),
            nn.BatchNorm2d(img_dimension * 4),
            nn.ReLU(True),
            nn.ConvTranspose2d(img_dimension * 4, img_dimension * 2, 4, 2, 1, bias=False),
            nn.BatchNorm2d(img_dimension * 2),
            nn.ReLU(True),
            nn.ConvTranspose2d(img_dimension * 2,     img_dimension, 4, 2, 1, bias=False),
            nn.BatchNorm2d(img_dimension),
            nn.ReLU(True),
            nn.ConvTranspose2d(img_dimension,      3, 4, 2, 1, bias=False),
            # nn.Sigmoid()
        )

    def forward(self, input):
        return self.main( input )

    
class ImageDiscriminator(nn.Module):
    def __init__(
            self,
            ):

        super(ImageDiscriminator, self).__init__()
        self.conv1 = nn.Conv2d(3, 64, 4, 2, 1, bias=False)
        self.relu1 = nn.LeakyReLU(0.2, inplace=True)

        self.conv2 = nn.Conv2d(64, 64 * 2, 4, 2, 1, bias=False)
        self.bn2 = nn.BatchNorm2d(64 * 2)
        self.relu2 = nn.LeakyReLU(0.2, inplace=True)

        self.conv3 = nn.Conv2d(64 * 2, 64 * 4, 4, 2, 1, bias=False)
        self.bn3 = nn.BatchNorm2d(64 * 4)
        self.relu3 = nn.LeakyReLU(0.2, inplace=True)

        self.conv4 = nn.Conv2d(64 * 4, 64 * 8, 4, 2, 1, bias=False)
        self.bn4 = nn.BatchNorm2d(64 * 8)
        self.relu4 = nn.LeakyReLU(0.2, inplace=True)

        self.conv5 = nn.Conv2d(64 * 8, 1, 4, 1, 0, bias=False)

    def forward(self, input):
        conv1 = self.conv1( input )
        relu1 = self.relu1( conv1 )

        conv2 = self.conv2( relu1 )
        bn2 = self.bn2( conv2 )
        relu2 = self.relu2( bn2 )

        conv3 = self.conv3( relu2 )
        bn3 = self.bn3( conv3 )
        relu3 = self.relu3( bn3 )

        conv4 = self.conv4( relu3 )
        bn4 = self.bn4( conv4 )
        relu4 = self.relu4( bn4 )

        conv5 = self.conv5( relu4 )

        return torch.sigmoid( conv5 ), [relu2, relu3, relu4]

class Discriminator(nn.Module):
    def __init__(
            self,
            ):

        super(Discriminator, self).__init__()
        self.conv1 = nn.Conv2d(3, 64, 4, 2, 1, bias=False)
        self.relu1 = nn.LeakyReLU(0.2, inplace=True)

        self.conv2 = nn.Conv2d(64, 64 * 2, 4, 2, 1, bias=False)
        self.bn2 = nn.BatchNorm2d(64 * 2)
        self.relu2 = nn.LeakyReLU(0.2, inplace=True)

        self.conv3 = nn.Conv2d(64 * 2, 64 * 4, 4, 2, 1, bias=False)
        self.bn3 = nn.BatchNorm2d(64 * 4)
        self.relu3 = nn.LeakyReLU(0.2, inplace=True)

        self.conv4 = nn.Conv2d(64 * 4, 64 * 8, 4, 2, 1, bias=False)
        self.bn4 = nn.BatchNorm2d(64 * 8)
        self.relu4 = nn.LeakyReLU(0.2, inplace=True)

        self.conv5 = nn.Conv2d(64 * 8, 1, 4, 1, 0, bias=False)

    def forward(self, input):
        conv1 = self.conv1( input )
        relu1 = self.relu1( conv1 )

        conv2 = self.conv2( relu1 )
        bn2 = self.bn2( conv2 )
        relu2 = self.relu2( bn2 )

        conv3 = self.conv3( relu2 )
        bn3 = self.bn3( conv3 )
        relu3 = self.relu3( bn3 )

        conv4 = self.conv4( relu3 )
        bn4 = self.bn4( conv4 )
        relu4 = self.relu4( bn4 )

        conv5 = self.conv5( relu4 )

        return torch.sigmoid( conv5 ), [relu2, relu3, relu4]

class Generator(nn.Module):
    def __init__(
            self,
            extra_layers=False
            ):

        super(Generator, self).__init__()

        if extra_layers == True:
            self.main = nn.Sequential(
                nn.Conv2d(3, 64, 4, 2, 1, bias=False),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(64, 64 * 2, 4, 2, 1, bias=False),
                nn.BatchNorm2d(64 * 2),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(64 * 2, 64 * 4, 4, 2, 1, bias=False),
                nn.BatchNorm2d(64 * 4),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(64 * 4, 64 * 8, 4, 2, 1, bias=False),
                nn.BatchNorm2d(64 * 8),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(64 * 8, 100, 4, 1, 0, bias=False),
                nn.BatchNorm2d(100),
                nn.LeakyReLU(0.2, inplace=True),

                nn.ConvTranspose2d(100, 64 * 8, 4, 1, 0, bias=False),
                nn.BatchNorm2d(64 * 8),
                nn.ReLU(True),
                nn.ConvTranspose2d(64 * 8, 64 * 4, 4, 2, 1, bias=False),
                nn.BatchNorm2d(64 * 4),
                nn.ReLU(True),
                nn.ConvTranspose2d(64 * 4, 64 * 2, 4, 2, 1, bias=False),
                nn.BatchNorm2d(64 * 2),
                nn.ReLU(True),
                nn.ConvTranspose2d(64 * 2,     64, 4, 2, 1, bias=False),
                nn.BatchNorm2d(64),
                nn.ReLU(True),
                nn.ConvTranspose2d(    64,      3, 4, 2, 1, bias=False),
                nn.Sigmoid()
            )


        if extra_layers == False:
            self.main = nn.Sequential(
                nn.Conv2d(3, 64, 4, 2, 1, bias=False),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(64, 64 * 2, 4, 2, 1, bias=False),
                nn.BatchNorm2d(64 * 2),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(64 * 2, 64 * 4, 4, 2, 1, bias=False),
                nn.BatchNorm2d(64 * 4),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(64 * 4, 64 * 8, 4, 2, 1, bias=False),
                nn.BatchNorm2d(64 * 8),
                nn.LeakyReLU(0.2, inplace=True),

                nn.ConvTranspose2d(64 * 8, 64 * 4, 4, 2, 1, bias=False),
                nn.BatchNorm2d(64 * 4),
                nn.ReLU(True),
                nn.ConvTranspose2d(64 * 4, 64 * 2, 4, 2, 1, bias=False),
                nn.BatchNorm2d(64 * 2),
                nn.ReLU(True),
                nn.ConvTranspose2d(64 * 2,     64, 4, 2, 1, bias=False),
                nn.BatchNorm2d(64),
                nn.ReLU(True),
                nn.ConvTranspose2d(    64,      3, 4, 2, 1, bias=False),
                nn.Sigmoid()
            )

    def forward(self, input):
        return self.main( input )

