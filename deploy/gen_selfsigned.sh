#!/usr/bin/env bash
# 生成自签证书（内网演示/测试用；正式交付换 CA 证书）
#   bash deploy/gen_selfsigned.sh 192.168.8.40
set -euo pipefail
cd "$(dirname "$0")"

HOST="${1:-localhost}"
mkdir -p certs
if [ -f certs/server.crt ]; then
  echo "certs/ 已存在，跳过。要重生成先删掉 certs/"
  exit 0
fi

openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
  -keyout certs/server.key -out certs/server.crt \
  -subj "/CN=${HOST}" \
  -addext "subjectAltName=DNS:${HOST},IP:${HOST}" 2>/dev/null

chmod 600 certs/server.key
echo "已生成 certs/server.crt 与 certs/server.key（10 年有效）"
echo "启用 TLS：docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d"
