#!/bin/bash

set -e
set -x

# Modify as required
num_client_nodes=7
num_db_nodes=13

benchmark_client_label="node-role.kubernetes.io/benchmark-client"
db_node_label="node-role.kubernetes.io/db-node"

required_nodes=$(($num_client_nodes+$num_db_nodes))

# Grab all of the nodes
nodes=(`kubectl get nodes --no-headers | grep -v control-plane | awk '{print $1}'`)

# Check we have enough
num_nodes="${#nodes[@]}"
if [ $num_nodes -lt $required_nodes ]; then
  echo "Not enough nodes (we only have $num_nodes) for $num_client_nodes benchmark clients and $num_db_nodes DB (TiKV/FDB) nodes"
  exit 1
fi

# Remove any existing labels
kubectl label nodes --all ${db_node_label}-
kubectl label nodes --all ${benchmark_client_label}-
kubectl label nodes --all node-role.kubernetes.io/pd-
kubectl label nodes --all node-role.kubernetes.io/tikv-

# Label the client nodes
for ((i=0;i<$num_client_nodes; ++i))
do
  echo "Setting ${nodes[$i]} as benchmark-client node"
  kubectl label node ${nodes[$i]} ${benchmark_client_label}=true
done

# Label the DB nodes
for ((i=$num_client_nodes;i<$num_client_nodes+$num_db_nodes; ++i))
do
  echo "Setting ${nodes[$i]} as DB node"
  kubectl label node ${nodes[$i]} ${db_node_label}=true
done
