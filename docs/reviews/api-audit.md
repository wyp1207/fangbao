# 接口审计：后端有，前端调没调

后端路由 166 个，**前端未发现调用 19 个**。

> 判定：扫 web/src 里的 `/api/v1/...`、`request('/...')`、模板字符串路径；
> 路由参数按通配匹配。命中的路径都算「有人用」（含 `<img src>`、导出链接）。

## 未调用清单

| 方法 | 路径 | 分类 | 说明 | 所在文件 |
|---|---|---|---|---|
| GET | `/ai/results/{result_id}/image` | 外部 | 视觉算法箱返回的图片，前端用 result.image_url | server/app/api/v1/ai.py |
| GET | `/alarms/latest` | 待接 | 老接口，前端已改用 /alarms 列表 | server/app/api/v1/alarms.py |
| POST | `/devices/reload` | 待接 | 改设备台账后重建轮询；后端已在 PATCH 里自动重建，前端无需调 | server/app/api/v1/devices.py |
| POST | `/devices/{device_id}/status-probe` | 待接 | 单设备探测，设备页可加「测试连接」按钮 | server/app/api/v1/devices.py |
| GET | `/ready` | 运维 | 就绪探针 | server/app/api/v1/health.py |
| GET | `/api/v1/health/deep` | 运维 | 健康检查脚本 | server/app/api/v1/health.py |
| PATCH | `/inspection/plans/{plan_id}` | 待接 | 人工巡检计划编辑入口未做 | server/app/api/v1/inspection.py |
| DELETE | `/inspection/plans/{plan_id}` | 待接 | 人工巡检计划删除入口未做 | server/app/api/v1/inspection.py |
| GET | `/inspection/photos/{path:path}` | 外部 | 照片 URL 由后端拼好，前端只贴 url | server/app/api/v1/inspection.py |
| POST | `/maps/library/points/{point_id}/sync` | 待接 | 点位同步到机器人，地图页暂无按钮 | server/app/api/v1/map_library.py |
| GET | `/metrics` | 运维 | Prometheus 抓 /metrics，前端不调 | server/app/api/v1/metrics.py |
| DELETE | `/recordings/{video_id}/all` | 待接 | 批量删录像，回放页暂无入口 | server/app/api/v1/recordings.py |
| GET | `/robots/runtime` | 待接 | 设备运行时总览，建议接到设备页顶部 | server/app/api/v1/robots.py |
| GET | `/robots/{robot_id}/pose` | 待接 | 位姿单独接口；首页已用 /status 里的位姿，可不通 | server/app/api/v1/robots.py |
| POST | `/sensors/{sensor_id}/readings/ingest` | 外部 | 采集网关/第三方按 Key 推送 | server/app/api/v1/sensors.py |
| POST | `/task-runs/ingest` | 外部 | 外部系统回报任务状态 | server/app/api/v1/task_runs.py |
| GET | `/telemetry/rollup` | 待接 | 分钟级聚合，报表长区间可切到它 | server/app/api/v1/telemetry.py |
| GET | `/videos/{video_id}/live.jpg` | 待接 | 首页改用 mjpeg 后这个只剩兜底，保留 | server/app/api/v1/videos.py |
| GET | `/videos/streams/stats` | 待接 | 视频转码进程状态，运维页可展示 | server/app/api/v1/videos.py |

## 按分类汇总

- **运维**（3）：`GET /ready`、`GET /api/v1/health/deep`、`GET /metrics`
- **外部**（4）：`GET /ai/results/{result_id}/image`、`GET /inspection/photos/{path:path}`、`POST /sensors/{sensor_id}/readings/ingest`、`POST /task-runs/ingest`
- **待接**（12）：`GET /alarms/latest`、`POST /devices/reload`、`POST /devices/{device_id}/status-probe`、`PATCH /inspection/plans/{plan_id}`、`DELETE /inspection/plans/{plan_id}`、`POST /maps/library/points/{point_id}/sync`、`DELETE /recordings/{video_id}/all`、`GET /robots/runtime`、`GET /robots/{robot_id}/pose`、`GET /telemetry/rollup`、`GET /videos/{video_id}/live.jpg`、`GET /videos/streams/stats`

## 处理原则

- 运维/调试类（health、metrics、probe）：保留，但要在文档里注明「仅运维用」
- 业务类且确实没人用：要么接到界面上，要么删掉——留着只会在验收时被问住
