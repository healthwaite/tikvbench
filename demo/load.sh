#!/bin/bash

set -x
set -e

TOTAL_KEYS=10000

NUM_THREADS=100
NUM_CLIENTS=15 # Must be less than or equal to the number of kvbench pods (see k8s/kvbench/kvbench.yaml)
BATCH_SIZE=20
DB=tikv

# Load the keys
./demo/scripts/run_benchmark.py \
  --num_clients=$NUM_CLIENTS \
  --num_threads=$NUM_THREADS \
  --db_type=$DB \
  --workload_file=./demo/workloads/base \
  --workload_action=load \
  --batch_size=$BATCH_SIZE \
  --keymax=$TOTAL_KEYS
