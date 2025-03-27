#!/usr/bin/python

import argparse
import subprocess
import json
import sys
import os
import re
import numpy as np

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

YCSB_BIN_PATH = "/go-ycsb"
WORKLOAD_FILE_PATH = "/workload"
TEMP_DIR = "/tmp"
OUTPUT_FILE_CONTAINER = "/output.txt"
RESULTS_FILE_CONTAINER = "/results.csv"


def run_command_retry(cmd, num_retries=3):
    while num_retries > 0:
        try:
            run_command(cmd, throw_if_fails=False)
            break
        except Exception as e:
            print(f"### Retrying command '{cmd}' {e}")
            num_retries -= 1
            if num_retries == 0:
                raise e


def run_command(cmd, throw_if_fails=True, debug=False):
    print("### Running", cmd)
    result = subprocess.run(cmd, capture_output=True, shell=True, text=True)
    if result.returncode != 0 and throw_if_fails:
        raise Exception(
            "Running command failed: {}\n stdout: {}\n stderr: {}\n".format(
                cmd, result.stdout, result.stderr
            )
        )

    if debug:
        print(stdout)
        print(stderr)

    return result.stdout.strip(), result.stderr.strip()


def enumerate_benchmark_pods():
    stdout, stderr = run_command('kubectl get pods -l "app=kvbench" -o json')
    pod_list_json = json.loads(stdout)
    return pod_list_json["items"]


def split_key_range(n, start_key, end_key):
    diff = int(end_key) - int(start_key)
    if diff < n:
        print(
            f"### Bogus key range [{start_key}-{end_key}] is smaller than the number of clients"
        )
        sys.exit(1)

    bin_size = diff // n
    remainder = diff % n

    # The first m bins get bin_size elements. The remaining bins get
    # binSize + 1
    key_ranges = []
    m = n - remainder
    for i in range(0, m):
        key_ranges.append((start_key, start_key + bin_size))
        start_key += bin_size

    for i in range(m, n):
        key_ranges.append((start_key, start_key + bin_size + 1))
        start_key += bin_size + 1

    return key_ranges


def run_commands_in_parallel(tasks):
    with ThreadPoolExecutor(max_workers=200) as executor:
        running_tasks = [executor.submit(task) for task in tasks]
        for running_task in running_tasks:
            running_task.result()


def build_ycsb_cmd(
    load_or_run,
    db_type,
    key_range,
    operation_count,
    workload_file,
    threads,
    measurement_type,
    container_results_file,
    batch_size,
    batch_wait,
    batch_wait_max,
    load_from_key,
    extra_args,
    read_proportion,
    update_proportion,
    delete_proportion,
    target_iops_per_client,
    duration,
):
    key_range_start, key_range_end = key_range[0], key_range[1]

    db_cmd = db_type
    if db_type == "tikv-txn":
        db_cmd = "tikv"

    if load_or_run == "load":
        key_range = key_range_end - key_range_start

        # If we are loading keys then ignore operation_count, we just load all the keys
        operation_count = key_range - load_from_key
        key_range_start += load_from_key
        cmd = f"""\
{YCSB_BIN_PATH} load {db_cmd} \
-P {workload_file} \
--threads {threads} \
-p insertstart={key_range_start} \
-p insertcount={operation_count} \
-p recordcount={key_range_end} \
-p batch.size={batch_size} \
-p tikv.batchwait={batch_wait} \
-p tikv.batchwaitmax={batch_wait_max}"""

    else:
        if read_proportion + update_proportion + delete_proportion != 1:
            print(
                "### read_proportion + update_proportion + delete_proportion must sum to 1.0"
            )
            sys.exit(1)

        cmd = f"""\
{YCSB_BIN_PATH} run {db_cmd} \
-P {workload_file} \
--threads {threads} \
-p insertstart={key_range_start} \
-p operationcount={operation_count} \
-p recordcount={key_range_end} \
-p batch.size={batch_size} \
-p tikv.batchwait={batch_wait} \
-p tikv.batchwaitmax={batch_wait_max} \
-p measurementtype={measurement_type} \
-p measurement.output_file={RESULTS_FILE_CONTAINER} \
-p readproportion={read_proportion} \
-p updateproportion={update_proportion} \
-p deleteproportion={delete_proportion}"""

    # Using TiKV in txn mode requires us to override some config
    if db_type == "tikv-txn":
        cmd += " -p tikv.type=txn"

    if extra_args:
        cmd += " " + extra_args

    if target_iops_per_client:
        cmd += " -p target=" + str(int(target_iops_per_client))

    if duration:
        cmd += " -p maxexecutiontime=" + duration

    return cmd


def build_ycsb_task(pod_name, ycsb_cmd):
    def task():
        # Run the benchmark
        cmd = f"kubectl exec {pod_name} -- bash -c '{ycsb_cmd} > {OUTPUT_FILE_CONTAINER} 2>&1'"
        stdout, _ = run_command(cmd)

    return task


def build_collect_result_task(results_dir, pod_name):
    def task():
        # Tar up the results
        cmd = f"kubectl exec {pod_name} -- tar -czvf x.tar.gz {OUTPUT_FILE_CONTAINER} {RESULTS_FILE_CONTAINER}"
        stdout, stderr = run_command(cmd)
        print(stdout)
        print(stderr)

        # Copy to results dir
        # kubectl cp is bad, it frequently fails and it's slow.
        cmd = f"kubectl cp --retries=5 {pod_name}:/x.tar.gz {results_dir}/x.tar.gz"
        run_command(cmd)

        # Unpack
        cmd = f"tar -xzvf {results_dir}/x.tar.gz -C {results_dir} ; rm {results_dir}/x.tar.gz"
        run_command(cmd)

    return task


def kill_all(bench_pods):
    tasks = []
    for pod in bench_pods:
        cmd = f"kubectl exec {pod} -- pkill -9 -f go-ycsb"
        task = lambda cmd=cmd: run_command(cmd, throw_if_fails=False)
        tasks.append(task)

    run_commands_in_parallel(tasks)


def create_results_dir():
    now = datetime.now()
    current_time = now.strftime("%Y%m%d-%H%M%S")
    path = f"/tmp/{current_time}"
    os.mkdir(path)
    return path


######################## MAIN #########################

# Parse args
parser = argparse.ArgumentParser()
parser.add_argument(
    "--num_clients", type=int, help="the number of clients to run", default=1
)
parser.add_argument(
    "--num_threads", type=int, help="the number of threads to run for each client"
)
parser.add_argument("--ops", type=int, help="operations per client")
parser.add_argument(
    "--db_type", type=str, help="the db type either 'http', 'tikv', 'tikv-txn' or 'fdb'"
)
parser.add_argument("--workload_file", type=str, help="the workload file")
parser.add_argument(
    "--workload_action", type=str, help="whether to 'load' or 'run'", default="load"
)
parser.add_argument(
    "--keymax",
    type=int,
    help="the maximum key, the keyspace [0-keymax] is shared equally over `num_clients`",
)
parser.add_argument(
    "--batch_size", type=int, help="the batch size (for tikv db types only)", default=1
)
parser.add_argument(
    "--batch_wait",
    type=str,
    help="the batch wait (for tikv db types only",
    default="0s",
)
parser.add_argument(
    "--batch_wait_max",
    type=int,
    help="the batch wait max (for tikv db types only)",
    default="8",
)
parser.add_argument(
    "--measurement_type",
    type=str,
    help="'raw', 'csv-file' or 'histogram'",
    default="raw",
)
parser.add_argument(
    "--pkill", type=bool, help="run pkill go-ycsb then exit", default=False
)
parser.add_argument(
    "--extra",
    type=str,
    help="extra 'go-ycsb' args e.g. \"-p tikv.conncount=4 -p tikv.xxx=foo\"",
)
parser.add_argument(
    "--key_offset",
    type=int,
    help="the keyspace is defined as [key_offset, key_offset+key_max]",
    default=0,
)
parser.add_argument(
    "--load-from-key",
    type=int,
    help="if a load benchmark fails you want to pick off from where \
you left off, 'load-from-key' should be the number of keys that were \
successfully loaded before the benchmark crashed, we'll begin reloading from here",
    default=0,
)
parser.add_argument(
    "--read_proportion", type=float, help="the proportion of reads to do", default=0.0
)
parser.add_argument(
    "--update_proportion",
    type=float,
    help="the proportion of inserts to do",
    default=0.0,
)
parser.add_argument(
    "--delete_proportion",
    type=float,
    help="the proportion of deletes to do",
    default=0.0,
)
parser.add_argument(
    "--target",
    type=int,
    help="the target iops to hit (0 means as fast as possible)",
    default=0,
)
parser.add_argument(
    "--duration",
    type=str,
    help="how long to run the benchmark for, you can not specify this argument and '--ops'",
)
parser.add_argument(
    "--collect_results",
    type=bool,
    default=False,
    help="whether we should collect latency measurements from the benchmark pods (warning: if you are doing a big benchmark then this will generate a LOT of data)",
)

args = parser.parse_args()

# If the pkill arg is specifed simply run pkill on all the pods then exit
if args.pkill:
    bench_pods = enumerate_benchmark_pods()
    all_pods = [p["metadata"]["name"] for p in bench_pods]
    kill_all(all_pods)
    sys.exit(0)

if not args.keymax:
    print("Must specify --keymax argument")
    sys.exit(1)

# Check the measurement_type is legit
allowed_measurement_types = ["histogram", "raw", "csv-file"]
if args.measurement_type not in allowed_measurement_types:
    print(f"### Unknown measurement_type '{args.measurement_type}'")
    sys.exit(1)

# Check the db action is legit
allowed_actions = ["load", "run"]
if args.workload_action not in allowed_actions:
    print(f"### Unknown action '{args.workload_action}'")
    sys.exit(1)

# Check db type is legit
allowed_dbs = ["http", "tikv", "fdb", "tikv-txn"]
if args.db_type not in allowed_dbs:
    print(f"### Unknown db_type '{db_type}'")
    sys.exit(1)

# Grab the list of kvbench pods
bench_pods = enumerate_benchmark_pods()
if len(bench_pods) < args.num_clients:
    print(
        "### Num of kubernetes kvbench pods ({}) does not match num-clients ({})".format(
            len(bench_pods), args.num_clients
        )
    )
    sys.exit(1)


# Kill all instances of the benchmark which may still be running
all_pods = [p["metadata"]["name"] for p in bench_pods]
kill_all(all_pods)

# Only run on n pods
pods_to_run_on = all_pods[: args.num_clients]

# Copy the workload file over to each pod
task_list = []
for pod_name in pods_to_run_on:
    cmd = "kubectl cp {} {}:{}".format(args.workload_file, pod_name, WORKLOAD_FILE_PATH)
    task_list.append(lambda cmd=cmd: run_command(cmd))

run_commands_in_parallel(task_list)

# Create a directory to hold benchmark results
# Add a symlink in the local directory for ease of use
results_dir_root = create_results_dir()
if os.path.islink("latest"):
    os.unlink("latest")
os.symlink(results_dir_root, "latest")

num_clients = len(pods_to_run_on)
start_key = args.key_offset
end_key = args.key_offset + args.keymax
key_ranges = split_key_range(num_clients, start_key, end_key)

if args.ops and args.duration:
    print("### Can't specify --ops and --duration")
    sys.exit(1)

# Now run the test
run_bench_tasks = []
collect_results_tasks = []
start_key = 0

target_iops_per_client = 0
if args.target:
    target_iops_per_client = args.target / num_clients

for pod_name, key_range in zip(pods_to_run_on, key_ranges):
    operation_count = args.ops
    if args.duration:
        operation_count = 99999999999

    # Create a directory to store stdout/stderr, and the raw benchmark data
    results_dir = f"{results_dir_root}/{pod_name}"
    os.mkdir(results_dir)

    container_results_file = f"/{pod_name}-bench-results.txt"
    cmd = build_ycsb_cmd(
        load_or_run=args.workload_action,
        db_type=args.db_type,
        key_range=key_range,
        operation_count=operation_count,
        workload_file=WORKLOAD_FILE_PATH,
        threads=args.num_threads,
        measurement_type=args.measurement_type,
        container_results_file=container_results_file,
        batch_size=args.batch_size,
        batch_wait=args.batch_wait,
        batch_wait_max=args.batch_wait_max,
        load_from_key=args.load_from_key,
        extra_args=args.extra,
        read_proportion=args.read_proportion,
        update_proportion=args.update_proportion,
        delete_proportion=args.delete_proportion,
        target_iops_per_client=target_iops_per_client,
        duration=args.duration,
    )

    task = build_ycsb_task(pod_name, cmd)
    run_bench_tasks.append(task)

    if args.collect_results and args.measurement_type == "csv-file":
        task = build_collect_result_task(results_dir=results_dir, pod_name=pod_name)
        collect_results_tasks.append(task)

start_time = datetime.now().isoformat()
run_commands_in_parallel(run_bench_tasks)
run_commands_in_parallel(collect_results_tasks)

# Copy the command line
filename = f"{results_dir_root}/cmd.txt"
f = open(filename, "w")
cmd_line = " ".join(arg for arg in sys.argv)
f.write(cmd_line)
f.close()

# Dump the start time
filename = f"{results_dir_root}/time.txt"
f = open(filename, "w")
f.write(str(start_time))
f.close()

# Dump various useful cluster info
os.system(f"kubectl get pods -o yaml -A > {results_dir_root}/pods.yaml")
os.system(f"kubectl get pvc -o yaml -A > {results_dir_root}/pvc.yaml")
os.system(f"kubectl get statefulsets -A > {results_dir_root}/statefulsets.yaml")
os.system(f"cp {args.workload_file} {results_dir_root}/workload")
