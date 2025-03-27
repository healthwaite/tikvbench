#!/bin/bash

set -x
set -e

TOTAL_KEYS=10000000000 # Must be the same as in load.sh

NUM_THREADS=${NUM_THREADS:-800}
NUM_CLIENTS=${NUM_CLIENTS:-15} # Must be less than or equal to the number of kvbench pods (see k8s/kvbench/kvbench.yaml)
RUNTIME=${RUNTIME:-20m}
TARGET_IOPS=${TARGET_IOPS:-0}
BATCH_SIZE=${BATCH_SIZE:-1}
BATCH_WAIT=${BATCH_WAIT:-10ms}
BATCH_WAIT_MAX=${BATCH_WAIT_MAX:-128}
DB=tikv

# Setup somewhere to stash the results
results_dir="/results/kvbench-`date +%Y%m%d-%H%M%S`"
sudo mkdir -p $results_dir
sudo chmod 777 $results_dir

# Take a copy of this script
script_dir="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"
script_path="${script_dir}/$(basename "$0")"
cp $script_path $results_dir

extra_args=""
if [ "$BENCH_TYPE" == "read" ]; then
  extra_args="--read_proportion=1.0"
elif [ "$BENCH_TYPE" == "update" ]; then
  extra_args="--update_proportion=1.0"
elif [ "$BENCH_TYPE" == "mixed" ]; then
  extra_args="--read_proportion=0.50 --update_proportion=0.50"
else
  echo "You must set BENCH_TYPE"
  exit 1
fi

# Run the benchmark
./demo/scripts/run_benchmark.py \
  --num_clients=$NUM_CLIENTS \
  --num_threads=$NUM_THREADS \
  --db_type=$DB \
  --workload_file=./demo/workloads/base \
  --duration=$RUNTIME \
  --workload_action=run \
  --measurement_type=csv-file \
  --batch_size=$BATCH_SIZE \
  --batch_wait=$BATCH_WAIT \
  --batch_wait_max=$BATCH_WAIT_MAX \
  --keymax=$TOTAL_KEYS \
  --target=$TARGET_IOPS \
  --collect_results true \
  ${extra_args}

# Copy the results
mkdir -p ${results_dir}/bench-$BENCH_TYPE
cp -rf latest/* ${results_dir}/bench-$BENCH_TYPE
