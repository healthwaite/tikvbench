#!/bin/bash

set -e
set -x

pushd go-ycsb

if [[ ! -z "$(git status -s)" ]]; then
  popd
  echo "You have uncommited changes in your go-ycsb submodule"
  exit 1
fi

if [[ -z ${DOCKER_REPOSITORY} ]]; then
  echo "You must set DOCKER_REPOSITORY"
  exit 1
fi

# Grab the commit ID of HEAD
COMMIT_SHA=$(git rev-parse --short=8 HEAD)
COMMIT_DATE=$(git log -1 --date=format:'%Y%m%d-%H%M%S' --format='%ad')

# Build go-ycsb
make build

popd > /dev/null

# Build the image
docker build -t $DOCKER_REPOSITORY/kvbench:$COMMIT_SHA-$COMMIT_DATE .
docker push $DOCKER_REPOSITORY/kvbench:$COMMIT_SHA-$COMMIT_DATE
