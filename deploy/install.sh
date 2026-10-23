#!/usr/bin/env bash
# 一键部署到 192.168.8.40（或任意装了 Docker 的机器）
#
#   bash deploy/install.sh            # 首次部署 / 升级
#   bash deploy/install.sh --recreate # 强制重建容器
#
# 做的事：
#   1. 检查 docker / compose
#   2. 准备 /data/jcrob-platform 目录（录像、地图、MySQL 数据）
#   3. 如果没有 deploy/env，从 env.example 生成并提醒改密码
#   4. 构建镜像 → 迁移由容器入口自动跑 → 起服务 → 等健康检查
set -euo pipefail

cd "$(dirname "$0")"
COMPOSE="docker compose --env-file env -f docker-compose.yml"
DATA_ROOT=/data/jcrob-platform

echo "== 1/5 环境检查 =="
docker version >/dev/null 2>&1 || { echo "没有 docker，先装 Docker"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "没有 docker compose 插件"; exit 1; }

echo "== 2/5 数据目录 =="
for d in recordings maps logs mysql; do
  mkdir -p "$DATA_ROOT/$d"
done
# 录像目录要给容器里的 appuser(10001) 写权限。
# 非 root 部署时 chown 会失败，退回 0777——内网单机可以接受，有 root 就用 chown。
if ! chown -R 10001:10001 "$DATA_ROOT/recordings" "$DATA_ROOT/maps" 2>/dev/null; then
  echo "  (非 root，无法 chown，改用 chmod 777 让容器能写)"
  # 有些旧文件是 root 建的，非 root 改不动；不能因为这个整脚本退出（set -e）
  chmod -R 777 "$DATA_ROOT/recordings" "$DATA_ROOT/maps" 2>/dev/null || true
fi
df -h "$DATA_ROOT" | tail -1

echo "== 3/5 配置文件 =="
if [ ! -f env ]; then
  cp env.example env
  echo "!! 已生成 deploy/env，请先改掉 JC_SECRET_KEY / JC_DB_PASSWORD / 密码，再重跑本脚本"
  echo "   openssl rand -hex 32   # 生成密钥"
  exit 1
fi
if grep -qE "please-change-this|please-change-on-first-login" env; then
  echo "!! deploy/env 里还是占位密钥，先改掉再部署"
  exit 1
fi

echo "== 4/5 构建镜像 =="
$COMPOSE build

echo "== 5/5 启动 =="
if [ "${1:-}" = "--recreate" ]; then
  $COMPOSE up -d --force-recreate
else
  $COMPOSE up -d
fi

echo "== 等待健康检查 =="
for i in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8099/health >/dev/null 2>&1; then
    echo "健康检查通过"
    break
  fi
  sleep 2
  if [ "$i" = "60" ]; then
    echo "!! 2 分钟没起来，看日志："
    $COMPOSE logs --tail=80 jc-server
    exit 1
  fi
done

PORT=$(docker port jc-nginx 80/tcp 2>/dev/null | head -1 | awk -F: '{print $NF}')
echo
echo "部署完成：http://$(hostname -I | awk '{print $1}'):${PORT:-8099}"
echo "账号：见 deploy/env 里的 JC_BOOTSTRAP_ADMIN / JC_BOOTSTRAP_PASSWORD"
echo "日志：$COMPOSE logs -f jc-server"
