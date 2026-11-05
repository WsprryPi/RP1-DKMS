# SPDX-License-Identifier: MIT
FROM docker.io/library/debian@sha256:c94f5ddd41327aa2d4a7cfba7889056c02936182fd76a513fec6160c97181fc0

COPY tools/lifecycle-headers.sha256 /opt/lifecycle-headers/SHA256SUMS

# Full payloads are needed for exact dpkg inventory validation.
RUN printf '%s\n' 'Acquire::Retries "2";' 'Acquire::http::Timeout "30";' 'Acquire::https::Timeout "30";' > /etc/apt/apt.conf.d/80-lifecycle-budgets \
    && rm /etc/dpkg/dpkg.cfg.d/docker \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential debhelper dh-dkms dkms adduser device-tree-compiler \
        python3 python3-jsonschema git gzip xz-utils bzip2 zstd openssl \
        shellcheck curl ca-certificates \
    && curl -fsSL --connect-timeout 30 --max-time 180 --retry 2 https://raw.githubusercontent.com/raspberrypi/rpi-image-gen/1f5851b24a6ac25b91edfaed5f2b59e770d0ac9e/keydir/raspberrypi-archive-keyring.gpg \
        -o /usr/share/keyrings/raspberrypi.gpg \
    && printf '%s\n' '3a29901549ae65a910de13a32551e6eea7f45ba1fd70f0cb67e5c70d98488071  /usr/share/keyrings/raspberrypi.gpg' | sha256sum -c - \
    && printf '%s\n' 'deb [signed-by=/usr/share/keyrings/raspberrypi.gpg] https://archive.raspberrypi.com/debian/ trixie main' \
        > /etc/apt/sources.list.d/raspberrypi.list \
    && apt-get update \
    && cd /opt/lifecycle-headers \
    && while read -r checksum package; do \
        case "$checksum" in \#*|'') continue ;; esac; \
        curl -fsSL --connect-timeout 30 --max-time 180 --max-filesize 134217728 --retry 2 \
            "https://archive.raspberrypi.com/debian/pool/main/l/linux/$package" -o "$package" || exit 1; \
       done < SHA256SUMS \
    && sha256sum -c SHA256SUMS \
    && apt-get install -y --no-install-recommends ./*.deb \
    && test "$(dpkg-query -W -f='${Version}' linux-headers-rpi-2712)" = '1:6.18.50-1+rpt1' \
    && test "$(dpkg-query -W -f='${Version}' linux-headers-rpi-v8)" = '1:6.18.50-1+rpt1' \
    && cd / \
    && rm -rf /opt/lifecycle-headers /var/lib/apt/lists/*

# Retain the official dependency archive for a real remove/repair dependency test.
RUN apt-get update \
    && mkdir -p /opt/lifecycle-inputs \
    && cd /opt/lifecycle-inputs \
    && apt-get download adduser \
    && rm -rf /var/lib/apt/lists/*
