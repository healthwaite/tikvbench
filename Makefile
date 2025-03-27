.PHONY: go-ycsb
go-ycsb:
	make -C go-ycsb

# Builds the benchmark container image and pushes it to DOCKER_REPOSITORY
.PHONY: bench-image
bench-image: go-ycsb
	./scripts/build_kvbench.sh
