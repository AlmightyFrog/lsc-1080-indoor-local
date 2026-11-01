# Cross-build for the cam. Runs only inside the pinned container
# (tools/Dockerfile); the `build` rule fails if the shipped binary stops
# reproducing byte-for-byte.
IMAGE := lsc-cam-build
CROSS := armv5l-linux-musleabi-
RUN   := docker run --rm -v "$(CURDIR)":/w -w /w \
         --user $(shell id -u):$(shell id -g) -e HOME=/tmp $(IMAGE)

.PHONY: all build clean

all:
	docker build -t $(IMAGE) -f tools/Dockerfile .
	$(RUN) make build

build: clean
	$(CROSS)gcc -O2 -static tools/motiond.c -o tools/motiond
	$(CROSS)gcc -O2 -static tools/hello.c -o tools/hello
	cmp tools/motiond card/custom/bin/motiond \
	  && echo "OK: rebuild byte-identical to shipped binary"

clean:
	rm -f tools/motiond tools/hello
