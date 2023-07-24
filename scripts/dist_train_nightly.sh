#!/usr/bin/env bash

GPUS=$1
CONFIG=$2
# PORT=${PORT:-1321}
PORT=${PORT:-$((1111 + $RANDOM % 10))}

# usage
if [ $# -lt 2 ] ;then
    echo "usage:"
    echo "./scripts/dist_train.sh [number of gpu] [path to option file]"
    exit
fi

# PYTHONPATH="$(dirname $0)/..:${PYTHONPATH}" \
#python3 -m torch.distributed.launch --nproc_per_node=$GPUS --master_port=$PORT \
#    basicsr/train.py -opt $CONFIG --launcher pytorch ${@:3}
#

python3 -m torch.distributed.launch --nproc-per-node=$GPUS basicsr/train.py -opt $CONFIG