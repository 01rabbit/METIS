FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pil python3-pydantic openssh-server openssh-client sshpass \
    xrdp xorgxrdp xserver-xorg-core freerdp2-x11 \
    tigervnc-standalone-server tigervnc-viewer tigervnc-tools \
    xvfb xauth xterm x11-apps x11-xserver-utils xfonts-base openvpn openssl iproute2 curl procps \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -s /bin/bash analyst && mkdir -p /run/sshd
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /repo
COPY src/metis/ /repo/metis/
COPY tests/blue_lab/*.py /repo/tests/blue_lab/
CMD ["python3", "tests/blue_lab/server.py"]
