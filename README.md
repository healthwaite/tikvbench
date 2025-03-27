# tikvbench

## Overview

This repo accompanies the demo as shown in the Kubecon London 2025 talk
[Stateful Superpowers: Explore High Performance and Scaleable Stateful Workloads
on K8s - Alex Chircop, Chris Milsted & Alex Reid, Akamai; Lori Lorusso,
Percona](https://kccnceu2025.sched.com/event/1txEs/stateful-superpowers-explore-high-performance-and-scaleable-stateful-workloads-on-k8s-alex-chircop-chris-milsted-alex-reid-akamai-lori-lorusso-percona). It provides
some scripts to spin up a TiKV cluster and then benchmark it using go-ycsb.

## Prerequisites

1. A kubernetes cluster! By default this repo expects you have 20 nodes: 13 for
   TiKV and 7 for the benchmark clients. If you have a different amount then
   modify `num_client_nodes` and `num_db_nodes` in `./scripts/label_node.sh`.
   You'll also need to modify the number of tikv replicas in `k8s/tikv/tikv-cluster.yaml`
   and `num_tikv_nodes` in `scripts/deploy_tikv.sh`.
2. To achieve the best peformance you want to be using local disks. These
   scripts expect that you have created a storage class called `ssd-storage`
   which is backed by the local disks. You can do this using the [Local Peristence Volume Static Provisioner](https://github.com/kubernetes-sigs/sig-storage-local-static-provisioner#local-persistence-volume-static-provisioner),
   for example.

## Installing the TiKV cluster

First we'll label the nodes so there are 13 for TiKV (12 for storage and one for
the pd pod) and 7 for the benchmark
client:

```
export KUBECONFIG=<path_to_kubeconfig>
$ ./scripts/label_nodes.sh
```

Check the output:

```
$ kubectl get nodes
NAME                            STATUS   ROLES              AGE   VERSION
lke375176-580277-00b103370000   Ready    benchmark-client   10d   v1.32.1
lke375176-580277-06adc13b0000   Ready    benchmark-client   10d   v1.32.1
lke375176-580277-0a90f5770000   Ready    benchmark-client   10d   v1.32.1
lke375176-580277-0e29b9970000   Ready    benchmark-client   10d   v1.32.1
lke375176-580277-124f08480000   Ready    benchmark-client   10d   v1.32.1
lke375176-580277-20cd2fe80000   Ready    benchmark-client   10d   v1.32.1
lke375176-580277-2e9029440000   Ready    benchmark-client   10d   v1.32.1
lke375176-580277-381bb3010000   Ready    db-node,pd         10d   v1.32.1
lke375176-580277-4042fa710000   Ready    db-node,tikv       10d   v1.32.1
lke375176-580277-43c37cff0000   Ready    db-node,tikv       10d   v1.32.1
lke375176-580277-4447e9a90000   Ready    db-node,tikv       10d   v1.32.1
lke375176-580277-463a5a580000   Ready    db-node,tikv       10d   v1.32.1
lke375176-580277-53184bcc0000   Ready    db-node,tikv       10d   v1.32.1
lke375176-580277-531a5e310000   Ready    db-node,tikv       10d   v1.32.1
lke375176-580277-53ee523d0000   Ready    db-node,tikv       10d   v1.32.1
lke375176-580277-582f52400000   Ready    db-node,tikv       10d   v1.32.1
lke375176-580277-5968edd70000   Ready    db-node,tikv       10d   v1.32.1
lke375176-580277-5babed820000   Ready    db-node,tikv       10d   v1.32.1
lke375176-580277-5d135ecb0000   Ready    db-node,tikv       10d   v1.32.1
lke375176-580277-6448ab1b0000   Ready    db-node,tikv       10d   v1.32.1
```

If you want to modify the number of replicas, tikv storage pods, etc. then
modify `k8s/tikv/tikv-cluster.yaml`. Finally run the following command to
install the TiKV CRDs, operator and finally the TiKV cluster:

```
$ ./scripts/deploy_tikv.sh
```

Wait for the cluster to be installed and made ready:

```
$ kubectl get tidbcluster -n tikv-cluster
NAME    READY   PD                  STORAGE   READY   DESIRE   TIKV                  STORAGE   READY   DESIRE   TIDB   READY   DESIRE   AGE
basic   True    pingcap/pd:v7.1.2   100Gi     2       2        pingcap/tikv:v7.1.2   500Gi     12      12                               78m
```

## Accessing the Grafana

To access the TiKV grafana instance which comes with all the preinstalled
dashboards run the following command:

```
$ kubectl -n tikv-cluster port-forward svc/basic-grafana 3000:3000
```

Then browse to http://127.0.0.1:3000 and login with credentials `admin/admin`.


## Preparing the benchmark

First we need to start the benchmark client pods. These pods are run as a
statefulset in the default namespace:

```
$ kubectl create -f k8s/kvbench
```

Check all 15 pod are up and running:
```
$ kubectl get statefulset
NAME      READY   AGE
kvbench   15/15   42m
```

Before running a benchmark it's sensible to preload some keys. You can do this
with the `./demo/load.sh` script. The script loads 10 billion keys by default
but you can modify this by changing the `TOTAL_KEYS` variable. It's safe to
CTRL-C the script once you've started. The key load will continue in the
background:

```
$ ./demo/load.sh
+ set -e
+ TOTAL_KEYS=10000000000
+ NUM_THREADS=100
+ NUM_CLIENTS=15
+ BATCH_SIZE=20
+ DB=tikv
+ ./demo/scripts/run_benchmark.py --num_clients=15 --num_threads=100 --db_type=tikv --workload_file=./demo/workloads/base --workload_action=load --batch_size=20 --keymax=10000
### Running kubectl get pods -l "app=kvbench" -o json
### Running kubectl exec kvbench-0 -- pkill -9 -f go-ycsb
### Running kubectl exec kvbench-1 -- pkill -9 -f go-ycsb
### Running kubectl exec kvbench-10 -- pkill -9 -f go-ycsb
### Running kubectl exec kvbench-11 -- pkill -9 -f go-ycsb
### Running kubectl exec kvbench-12 -- pkill -9 -f go-ycsb
### Running kubectl exec kvbench-13 -- pkill -9 -f go-ycsb
### Running kubectl exec kvbench-14 -- pkill -9 -f go-ycsb
### Running kubectl exec kvbench-2 -- pkill -9 -f go-ycsb
### Running kubectl exec kvbench-3 -- pkill -9 -f go-ycsb
### Running kubectl exec kvbench-4 -- pkill -9 -f go-ycsb
### Running kubectl exec kvbench-5 -- pkill -9 -f go-ycsb
### Running kubectl exec kvbench-6 -- pkill -9 -f go-ycsb
### Running kubectl exec kvbench-7 -- pkill -9 -f go-ycsb
### Running kubectl exec kvbench-8 -- pkill -9 -f go-ycsb
### Running kubectl exec kvbench-9 -- pkill -9 -f go-ycsb
...
```

If you want to kill the key loading at anypoint you can run
`./demo/scripts/run_benchmark.py --pkill`.

Keep an eye on the grafana dashboard to see when key loading has finished.
The easiest thing to do is look at `Cluster-TiKV-Details > RocksDB - kv >
Total keys`. Remember this number includes replication. So if you are loading
1 million keys and have 5-way replication you are looking for the number of
keys to read 5 million.

## Running the benchmarks

To run a benchmark you can use `./demo/run.sh`. The benchmark can controlled
with the following environment variables:
1. `NUM_THREADS`: the number of goroutines each benchmark client runs. This is
   somewhat analogous to setting the queue depth. Default: 800
1. `NUM_CLIENTS`: the number of benchmark clients to run. Default: 15.
1. `TARGET_IOPS`: attempt to run the benchmark at this number of IOPs. This is
   the aggregate number across all benchmark clients. Default: 0, meaning run as
   fast as we possibly can.
1. `BATCH_SIZE`: the number of requests we'll batch together at the application
   layer before sending to TiKV. Increasing this massively improves performance 
   for writes. Default: 1.
1. `BATCH_WAIT`: the maximum time the TiKV golang client will internally wait for
   a batch of requests before sending them to the TiKV server. Default: 10ms.
1. `BATCH_WAIT_MAX`: the maximum amount of requests the TiKV golang client will
   internally batch before sending them to the TiKV server. Default: 128.
   batch before sending at once. Default
1. `BENCH_TYPE`: either read, update (read/modify/write) or mixed.
1. `RUNTIME`: how long to run the test for. Default: 5m

Some examples:

```
# Random read test, targeting 1 million iops, running for 5 mins:
$ BENCH_TYPE=read TARGET_IOPS=10000 RUNTIME=5m ./demo/run.sh

# Random update test, targeting 300,000 iops, running for 5 mins
$ BENCH_TYPE=update TARGET_IOPS=10000 RUNTIME=5m ./demo/run.sh
```

One the benchmark is completed some results will be dumped into `/results`.
You can analyse the results by doing:

```
$ cd ./cmd
$ go run main.go --dir /results/kvbench-20250327-170837/bench-read
### Benchmark map[batch_size:1 duration:10 keymax:10000000000 num_clients:15 num_threads:800 target:10000]
### Starting at 2025-03-27T17:08:40.418699
### Num clients: 15
### Num threads: 800
### Target RPS: 10000
numclients15_numthreads800_readbench-read_target10000 READ: ave: 4 p50: 0 p90 0 p99: 178 total_time: 9 rps: 9992 num_errors: 13 (0.01%)
numclients15_numthreads800_readbench-read_target10000 TOTAL: 9992 RPS
```
