#!/usr/bin/env bash
# 生成 deploy/env（随机密钥），已存在则跳过。
#   bash deploy/setup_env.sh            # 首次生成
#   bash deploy/setup_env.sh --force    # 覆盖重生成（会换掉数据库密码，谨慎）
set -euo pipefail

cd "$(dirname "$0")"

if [ -f env ] && [ "${1:-}" != "--force" ]; then
  echo "deploy/env 已存在，跳过。要重新生成请加 --force"
  exit 0
fi

rand_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$1"
  else
    head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

SECRET=$(rand_hex 32)
DBP=$(rand_hex 12)
ROOTP=$(rand_hex 12)
ADMINP="Jcrob$(rand_hex 4)"

cp env.example env
sed -i "s|^JC_SECRET_KEY=.*|JC_SECRET_KEY=${SECRET}|" env
sed -i "s|^JC_DB_PASSWORD=.*|JC_DB_PASSWORD=${DBP}|" env
sed -i "s|^JC_DB_ROOT_PASSWORD=.*|JC_DB_ROOT_PASSWORD=${ROOTP}|" env
sed -i "s|^JC_BOOTSTRAP_PASSWORD=.*|JC_BOOTSTRAP_PASSWORD=${ADMINP}|" env

echo "已生成 deploy/env"
echo "  管理员账号: admin"
echo "  初始密码  : ${ADMINP}"
echo "首次登录后请立刻在「右上角头像 → 修改密码」里改掉。"
