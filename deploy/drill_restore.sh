#!/usr/bin/env bash
# MySQL 备份恢复演练（会真的删库再恢复，只在确认可丢弃数据时跑）
#
#   bash deploy/drill_restore.sh          # 演练：备份→删库→恢复→校验
#
# 生产上第一次上线后建议跑一次，确认"备份真的能恢复"而不是"以为能恢复"。
set -euo pipefail

cd "$(dirname "$0")"
COMPOSE="docker compose -f docker-compose.yml"
BACKUP_DIR="${1:-/tmp/jcrob-restore-drill}"

set -a
# shellcheck disable=SC1091
. ./env
set +a

echo "== 1/5 备份 =="
bash backup.sh "$BACKUP_DIR" | tail -5
DUMP=$(ls -t "$BACKUP_DIR"/jcrob-db-*.sql | head -1)
echo "   dump: $DUMP ($(du -h "$DUMP" | cut -f1))"

echo "== 2/5 记录恢复前状态 =="
BEFORE=$($COMPOSE exec -T jc-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e "SELECT COUNT(*) FROM jcrob.user"')
TABLES_BEFORE=$($COMPOSE exec -T jc-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=\"jcrob\""')
echo "   用户数=$BEFORE 表数=$TABLES_BEFORE"

echo "== 3/5 删库（模拟事故）=="
$COMPOSE exec -T jc-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "DROP DATABASE jcrob; CREATE DATABASE jcrob CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"'
LEFT=$($COMPOSE exec -T jc-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=\"jcrob\""')
echo "   删库后表数=$LEFT"

echo "== 4/5 从备份恢复 =="
$COMPOSE exec -T jc-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" jcrob' < "$DUMP"
echo "   恢复完成"

echo "== 5/5 重启服务并校验 =="
$COMPOSE restart jc-server >/dev/null
for i in $(seq 1 40); do
  if curl -fsS http://127.0.0.1:8099/health >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -s http://127.0.0.1:8099/health; echo

AFTER=$($COMPOSE exec -T jc-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e "SELECT COUNT(*) FROM jcrob.user"')
TABLES_AFTER=$($COMPOSE exec -T jc-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=\"jcrob\""')
LOGIN=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8099/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$JC_BOOTSTRAP_ADMIN\",\"password\":\"$JC_BOOTSTRAP_PASSWORD\"}")

echo "   恢复后：用户数=$AFTER 表数=$TABLES_AFTER 登录=$LOGIN"

if [ "$BEFORE" = "$AFTER" ] && [ "$TABLES_BEFORE" = "$TABLES_AFTER" ] && [ "$LOGIN" = "200" ]; then
  echo "== 演练通过 =="
else
  echo "== 演练失败：数据或登录对不上 ==" >&2
  exit 1
fi
