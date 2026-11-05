# SPDX-License-Identifier: MIT

FROM docker.io/library/debian@sha256:c94f5ddd41327aa2d4a7cfba7889056c02936182fd76a513fec6160c97181fc0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        debhelper \
        dh-dkms \
        device-tree-compiler \
        python3 \
        python3-jsonschema \
        git \
        gzip \
        xz-utils \
        shellcheck \
        zstd \
    && rm -rf /var/lib/apt/lists/*
