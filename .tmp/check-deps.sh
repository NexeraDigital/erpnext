#!/usr/bin/env bash
PKGS="python3.10-venv python3-venv python3-dev build-essential libmysqlclient-dev libssl-dev libffi-dev libcups2-dev libldap2-dev libsasl2-dev libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev libtiff-dev libfreetype6-dev pkg-config"
MISSING=()
for p in $PKGS; do
  if dpkg -s "$p" >/dev/null 2>&1; then
    echo "OK   $p"
  else
    echo "MISS $p"
    MISSING+=("$p")
  fi
done
echo "---"
if [ ${#MISSING[@]} -gt 0 ]; then
  echo "MISSING_PKGS=${MISSING[*]}"
else
  echo "ALL_PRESENT"
fi
