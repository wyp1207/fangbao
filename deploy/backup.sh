#!/usr/bin/env bash
# 备份：数据库 + 地图 + 设置，不带录像（录像按保留策略滚动，太重）
#
#   bash deploy/backup.sh            # 备份到 /data/jcrob-platform/backup
#   bash deploy/backup.sh /mnt/nas   # 备份到指定目录（建议挂 NAS）
#
# 建议加进 crontab：
#   0 2 * * * cd /opt/jcrob && bash deploy/backup.sh >> /var/log/jcrob-backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")"
DST="${1:-/data/jcrob-platform/backup}"
STAMP=$(date +%Y%m%d-%H%M%S)
KEEP_DAYS="${KEEP_DAYS:-14}"
COMPOSE="docker compose -f docker-compose.yml"

mkdir -p "$DST"

echo "[$(date '+%F %T')] 备份到 $DST"

# 1) 数据库：优先 mysqldump，容器不在就跳过并报错
if docker ps --format '{{.Names}}' | grep -qx jc-mysql; then
  ROOT_PWD=$(docker exec jc-mysql sh -c 'echo "$MYSQL_ROOT_PASSWORD"')
  docker exec jc-mysql sh -c "mysqldump -uroot -p'$ROOT_PWD' --single-transaction --routines jcrob" \
    > "$DST/jcrob-db-$STAMP.sql"
  echo "  数据库: jcrob-db-$STAMP.sql ($(du -h "$DST/jcrob-db-$STAMP.sql" | cut -f1))"
else
  echo "  !! jc-mysql 没在跑，跳过数据库备份" >&2
  exit 1
fi

# 2) 地图库（平台导入的图纸，丢了只能让客户重新给）
if [ -d /data/jcrob-platform/maps ]; then
  tar czf "$DST/jcrob-maps-$STAMP.tar.gz" -C /data/jcrob-platform maps
  echo "  地图: jcrob-maps-$STAMP.tar.gz"
fi

# 3) 配置（deploy/env 里有密钥，单独存，权限收窄）
if [ -f env ]; then
  tar czf "$DST/jcrob-env-$STAMP.tar.gz" env
  chmod 600 "$DST/jcrob-env-$STAMP.tar.gz"
  echo "  配置: jcrob-env-$STAMP.tar.gz（含密钥，注意保管）"
fi

# 4) 清理过期备份
find "$DST" -name 'jcrob-*-*.sql' -mtime +"$KEEP_DAYS" -delete 2>/dev/null || true
find "$DST" -name 'jcrob-*-*.tar.gz' -mtime +"$KEEP_DAYS" -delete 2>/dev/null || true

echo "[$(date '+%F %T')] 完成；当前备份："
ls -lh "$DST" | tail -5

echo
echo "恢复方法："
echo "  docker exec -i jc-mysql sh -c 'mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" jcrob' < jcrob-db-XXX.sql"
echo "  tar xzf jcrob-maps-XXX.tar.gz -C /data/jcrob-platform"
