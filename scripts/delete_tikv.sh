#!/bin/bash

kubectl delete -f k8s/tikv
kubectl -n tikv-cluster get pv -l app.kubernetes.io/namespace=tikv-cluster,app.kubernetes.io/managed-by=tidb-operator,app.kubernetes.io/instance=basic \
  -o name | xargs -I {} kubectl patch {} -p '{"spec":{"persistentVolumeReclaimPolicy":"Delete"}}'
kubectl -n tikv-cluster delete pvc -l app.kubernetes.io/instance=basic,app.kubernetes.io/managed-by=tidb-operator
kubectl -n tikv-cluster delete pv -l app.kubernetes.io/instance=basic,app.kubernetes.io/managed-by=tidb-operator
