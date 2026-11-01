# Reproducible ARMv5 cross toolchain for this repo's Makefile.
# Pinned: sha256 of the tarball that built the shipped binaries.
FROM debian:trixie-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl make tar gzip \
 && rm -rf /var/lib/apt/lists/*
RUN curl -fL -o /x.tgz https://musl.cc/armv5l-linux-musleabi-cross.tgz \
 && echo "c17a278b6824f642083e6e499cd2a5a432cb0a4c662092b62e5bd716e1fa329b  /x.tgz" | sha256sum -c - \
 && tar xzf /x.tgz -C /opt && rm /x.tgz
ENV PATH=/opt/armv5l-linux-musleabi-cross/bin:$PATH
