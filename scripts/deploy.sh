#!/usr/bin/env bash
# 一键部署（Linux，systemd）。用法：
#   sudo bash scripts/deploy.sh /opt/jc-robot 8099
# 做了什么：建 venv → 装依赖 → 迁移 → 建 systemd 服务 → 启动 → 健康检查
set -euo pipefail

APP_DIR="${1:-/opt/jc-robot}"
PORT="${2:-8099}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON_BIN:-python3}"

echo "== 1/6 检查 Python =="
"$PY" -V

echo "== 2/6 同步代码到 $APP_DIR =="
mkdir -p "$APP_DIR"
rsync -a --delete \
  --exclude '.git' --exclude 'node_modules' --exclude 'data' --exclude '.venv' \
  --exclude '__pycache__' --exclude 'dist' \
  "$REPO_DIR/server/" "$APP_DIR/server/"
mkdir -p "$APP_DIR/server/data/logs" "$APP_DIR/server/data/backups"

echo "== 3/6 建虚拟环境并装依赖 =="
if [ ! -d "$APP_DIR/.venv" ]; then "$PY" -m venv "$APP_DIR/.venv"; fi
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/server/requirements.txt"

echo "== 4/6 数据库迁移 =="
cd "$APP_DIR/server"
"$APP_DIR/.venv/bin/alembic" upgrade head || {
  echo "迁移失败：请检查 JC_DB_URL / 数据库是否可达"; exit 1; }

echo "== 5/6 安装 systemd 服务 =="
cat >/etc/systemd/system/jc-robot.service <<EOF
[Unit]
Description=JC Robot Inspection Platform
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR/server
Environment=JC_ENV=prod
Environment=JC_BIND=0.0.0.0:$PORT
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $PORT
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now jc-robot
systemctl restart jc-robot

echo "== 6/6 健康检查 =="
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "部署成功：http://127.0.0.1:$PORT/health"
    exit 0
  fi
  sleep 1
done
echo "健康检查失败，查看：journalctl -u jc-robot -n 100"
exit 1
