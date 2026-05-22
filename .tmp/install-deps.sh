#!/usr/bin/env bash
set -euo pipefail
echo "$SUDO_PASS" | sudo -S -p '' apt update -qq 2>&1 | tail -3
echo "$SUDO_PASS" | sudo -S -p '' DEBIAN_FRONTEND=noninteractive apt install -y \
  libffi-dev libcups2-dev libldap2-dev libsasl2-dev libxml2-dev libxslt1-dev \
  libjpeg-dev libtiff-dev libfreetype6-dev pkg-config 2>&1 | tail -10
echo "[deps] DONE"
