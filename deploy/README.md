# 部署说明（192.168.8.40）

平台是 **3 个容器 + 1 个端口**：`jc-nginx`（前端 + 反代）、`jc-server`（FastAPI）、`jc-mysql`。
宿主只暴露 **8099**，其他都在 `jc-net` 内部。

```
浏览器 ──8099──> jc-nginx ──/api/──> jc-server:8000 ──> jc-mysql:3306
                      └──/go2rtc/──> 宿主 go2rtc:1984（视频）
```

## 一次性准备

1. 装 Docker + compose 插件（8.40 上已有）。
2. 建数据目录（`install.sh` 会自动建）：
   ```
   /data/jcrob-platform/{recordings,maps,logs,mysql}
   ```
3. 拷仓库到 `/opt/jcrob`（或任意目录），进 `deploy/`：
   ```bash
   cp env.example env
   openssl rand -hex 32        # 填进 JC_SECRET_KEY
   vim env                     # 改密钥、数据库密码、引导管理员密码
   ```

**`deploy/env` 绝对不要提交到仓库**，`.gitignore` 已经忽略它。

## 部署 / 升级

```bash
bash deploy/install.sh              # 首次
bash deploy/install.sh --recreate   # 改了 nginx 配置或 env 时
```

脚本会：检查 docker → 建目录 → 检查 env 是否还是占位值 → 构建镜像 → `up -d` →
轮询 `/health` 最多 2 分钟。

数据库迁移由容器入口自动执行（`alembic upgrade head`），**迁移失败容器直接退出**，
不会带着半截库对外服务。看日志：

```bash
docker compose -f deploy/docker-compose.yml logs -f jc-server
```

## 视频（go2rtc）

宿主机上已有 go2rtc（192.168.8.40:1984）：

- 后端访问：`JC_GO2RTC_BASE=http://host.docker.internal:1984`
- 浏览器访问：`JC_GO2RTC_PUBLIC_BASE=/go2rtc`，由 nginx 反代到宿主的 1984

这样**不用把 1984 暴露到外面**，也没有跨域问题。确认 nginx 能通：

```bash
curl -I http://127.0.0.1:8099/go2rtc/api
```

## 录像

- 容器内路径 `/app/data/recordings`，宿主 `/data/jcrob-platform/recordings`
- 目录属主要给 `10001:10001`（容器里的 appuser），否则写不进去
- 保留策略在「系统设置 → 录像」里改（默认 30 天 / 800GB / 磁盘低于 5GB 自动停录）
- 镜像里已装 `ffmpeg`（录制与抓帧都靠它）

容量估算（1080p、2 Mbps）：约 **21 GB/天/路**。两路 30 天约 1.26 TB，
所以默认上限 800GB 会在 19 天左右开始滚动删除——要留满 30 天就把上限调大。

## 备份

需要备份的只有两处：

```bash
# 数据库
docker exec jc-mysql sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" jcrob' > jcrob-$(date +%F).sql
# 录像 + 地图
tar czf jc-data-$(date +%F).tar.gz -C /data/jcrob-platform recordings maps
```

录像量大，建议只备数据库和地图，录像按保留策略滚动即可。

## 常见问题

| 现象 | 排查 |
|---|---|
| 8099 打不开 | `docker ps` 看三个容器是否都在；`logs jc-nginx` |
| 登录 500 | 数据库没起来：`logs jc-mysql`，确认 `JC_DB_PASSWORD` 与 compose 一致 |
| 迁移失败 | `logs jc-server` 看 alembic 报错；不要手动改表，先修迁移 |
| 视频黑屏 | `curl 127.0.0.1:8099/go2rtc/api`；确认宿主 go2rtc 在跑、摄像头 RTSP 可达 |
| 录像不落盘 | `ls -ld /data/jcrob-platform/recordings` 属主是否 10001；`系统设置 → 录像` 是否开启 |
| 页面时间差 8 小时 | 容器 `TZ=Asia/Shanghai` 是否生效；MySQL `--default-time-zone=+08:00` |

## 回滚

```bash
docker compose -f deploy/docker-compose.yml down
docker tag jc-server:0.1.x jc-server:0.2.0   # 用上一版 tag
docker compose -f deploy/docker-compose.yml up -d
```

数据库降级：`alembic downgrade 0001`（会删掉 0002 新增的表，谨慎）。
