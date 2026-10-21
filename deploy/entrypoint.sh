#!/usr/bin/env sh
# 容器启动入口：先迁移，再起服务。
# 迁移失败就直接退出——宁可让容器起不来，也不要带着半个库对外服务。
set -eu

echo "[entrypoint] 数据库迁移..."
if ! alembic upgrade head; then
  echo "[entrypoint] 迁移失败，退出" >&2
  exit 1
fi

echo "[entrypoint] 启动 uvicorn（单 worker，后台循环都在进程内）"
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${JC_PORT:-8000}" \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips='*'
