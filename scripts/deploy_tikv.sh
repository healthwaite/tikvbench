#!/bin/bash

set -x

# Modify as required
num_pd_nodes=1
num_tikv_nodes=12

# Install TiDB Operator CRDs
kubectl create -f https://raw.githubusercontent.com/pingcap/tidb-operator/v1.5.2/manifests/crd.yaml

# Add the helm chars
helm repo add pingcap https://charts.pingcap.org/

# Install the advanced statefulset CRD
kubectl apply -f https://raw.githubusercontent.com/pingcap/tidb-operator/v1.5.3/manifests/advanced-statefulset-crd.v1.yaml

# Install the operator
kubectl create namespace tidb-admin
helm install --namespace tidb-admin tidb-operator pingcap/tidb-operator --version v1.5.3 -f values-tidb-operator.yaml

# Label the nodes such that n nodes are reserved for the PDs and m nodes are reserved for TiKV
# Only run on nodes which have the label node-role.kubernetes.io/db-node=true
nodes=(`kubectl get node -l node-role.kubernetes.io/db-node=true --no-headers | awk '{print $1}'`)
num_nodes="${#nodes[@]}"

if [ $num_nodes -lt $num_pd_nodes ]; then
  echo "Not enough nodes (we only have $num_nodes) for $num_pd_nodes PDs"
  exit 1
fi

if [ $num_nodes -lt $num_tikv_nodes ]; then
  echo "Not enough nodes (we only have $num_nodes) for $num_tikv_nodes PDs"
  exit 1
fi

# Remove any existing labels
kubectl label nodes --all node-role.kubernetes.io/pd-
kubectl label nodes --all node-role.kubernetes.io/tikv-

for ((i=0;i<$num_pd_nodes; ++i))
do
  echo "Setting ${nodes[$i]} as PD node"
  kubectl label node ${nodes[$i]} node-role.kubernetes.io/pd=true
done

for ((i=$num_pd_nodes;i<$(($num_pd_nodes+$num_tikv_nodes)); ++i))
do
  echo "Setting ${nodes[$i]} as TiKV node"
  kubectl label node ${nodes[$i]} node-role.kubernetes.io/tikv=true
done

## Install the cluster
kubectl create namespace tikv-cluster
kubectl -n tikv-cluster create -f k8s/tikv
