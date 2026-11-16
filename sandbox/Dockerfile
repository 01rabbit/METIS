# METIS dynamic-analysis sandbox image.
#
# Build for the host CPU (the default). Targets for another architecture, such
# as x86-64 binaries on Apple Silicon, run through QEMU user-mode with the cross
# libc below and are debugged with gdb-multiarch via QEMU's gdb stub, because
# ptrace is unavailable under Rosetta/QEMU translation.
#
# Build with `.venv/bin/metis sandbox build`; METIS records the resulting
# immutable image ID and refuses mutable tags. The container is started with no
# network, a read-only root, no capabilities and an unprivileged user, so the
# tools below are only available to challenge programs inside that boundary.
FROM debian:bookworm-slim

ARG DEBIAN_FRONTEND=noninteractive
# Required everywhere. Architecture-dependent extras (ltrace is not packaged for
# arm64 in bookworm; cross libcs vary) are optional and reported when missing.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-dev gcc libc6-dev \
      gdb gdb-multiarch strace file binutils patchelf \
      libc6-dbg qemu-user ca-certificates \
 && for pkg in ltrace libc6-amd64-cross libc6-i386-cross libc6-arm64-cross libc6-armhf-cross; do \
      apt-get install -y --no-install-recommends "$pkg" \
        || echo "METIS: optional package $pkg unavailable on $(dpkg --print-architecture)"; \
    done \
 && rm -rf /var/lib/apt/lists/*

# pwntools for local exploit development inside the sandbox (script mode).
RUN pip3 install --no-cache-dir --break-system-packages "pwntools>=4.12" \
 && python3 -c "import pwn" \
 && mkdir -p /work && chmod 1777 /work

ENV PWNLIB_NOTERM=1 LANG=C.UTF-8
USER 65534:65534
WORKDIR /work
