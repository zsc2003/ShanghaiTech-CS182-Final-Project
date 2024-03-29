import os
import sys
import json
import torch
import random
import logging
import argparse
import numpy as np
from tqdm import tqdm
from trainer import Trainer
import horovod.torch as hvd
from models import load_model
from data import DataLoaderMasifLigand
from functools import partialmethod
from easydict import EasyDict as edict

from LBSR.utils.helpers import set_seed, set_logger


def train(config):
    # get dataloader
    data = DataLoaderMasifLigand(config)
    
    # initialize model
    Model = load_model(config.model)
    model = Model(config)

    # initialize trainer
    trainer = Trainer(config, data, model)
    trainer.train()


def get_config():

    # parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, default='config.json')
    
    # logging arguments
    parser.add_argument('--run_name', type=str)
    parser.add_argument('--out_dir', type=str)
    parser.add_argument('--test_freq', type=int)
    parser.add_argument('--seed', type=int)
    parser.add_argument('--auto_resume', type=lambda x: eval(x))
    parser.add_argument('--mute_tqdm', type=lambda x: eval(x))
    # data arguments
    parser.add_argument('--data_dir', type=str)
    parser.add_argument('--processed_dir', type=str, default='./processed_masif')
    parser.add_argument('--train_split_file', type=str, default=None)
    parser.add_argument('--valid_split_file', type=str, default=None)
    parser.add_argument('--test_split_file', type=str, default=None)
    parser.add_argument('--use_chem_feat', type=lambda x: eval(x), default=True)
    parser.add_argument('--use_geom_feat', type=lambda x: eval(x), default=True)
    
    parser.add_argument('--batch_size', type=int)
    parser.add_argument('--num_data_workers', type=int)
    parser.add_argument('--num_gdf', type=int)
    # optimizer arguments
    parser.add_argument('--optimizer', type=str, choices=['Adam', 'AdamW'])
    parser.add_argument('--epochs', type=int)
    parser.add_argument('--warmup_epochs', type=int)
    parser.add_argument('--lr', type=float)
    parser.add_argument('--lr_scheduler', type=str, \
        choices=['PolynomialLRWithWarmup', 'CosineAnnealingLRWithWarmup'])
    parser.add_argument('--weight_decay', type=float)
    parser.add_argument('--clip_grad_norm', type=float)
    parser.add_argument('--fp16', type=lambda x: eval(x))
    # model-specific arguments
    model_names = ['HMR']
    parser.add_argument('--model', type=str, choices=model_names)
    args = parser.parse_args()
    
    # load default config
    with open(args.config) as f:
        config = json.load(f)
    
    # update config with user-defined args
    for arg in vars(args):
        if getattr(args, arg) is not None:
            model_name = arg[:arg.find('_')]
            if model_name in model_names:
                model_arg = arg[arg.find('_')+1:]
                config[model_name][model_arg] = getattr(args, arg)
            else:
                config[arg] = getattr(args, arg)
    
    return edict(config)


if __name__ == '__main__':
    # init config
    config = get_config()
    config.is_master = True
    config.device = 'cuda' if torch.cuda.is_available() else 'cpu'

    # init horovod for distributed training
    config.use_hvd = torch.cuda.device_count() > 1
    if config.use_hvd:
        hvd.init()
        torch.cuda.set_device(hvd.local_rank())
        config.is_master = hvd.local_rank() == 0
        config.num_GPUs = hvd.size() # for logging purposes
        assert hvd.size() == torch.cuda.device_count()
    
    # logging, attach the hook after automatic download from HDFS
    set_logger(os.path.join(config.out_dir, 'train.log'))
    if config.is_master:
        logging.info('==> Configurations')
        for key, val in sorted(config.items(), key=lambda x: x[0]):
            if isinstance(val, dict):
                for k, v in val.items():
                    logging.info(f'\t[{key}] {k}: {v}')
            else:
                logging.info(f'\t{key}: {val}')
    
    # set random seed
    set_seed(config.seed)
    
    # mute tqdm
    if config.mute_tqdm or not config.is_master:
        tqdm.__init__ = partialmethod(tqdm.__init__, disable=True)
    
    train(config)
