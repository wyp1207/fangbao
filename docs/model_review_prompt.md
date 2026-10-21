# 豆包 / GLM 评审提示词 v2

> 2026-10-20 重写。上一版（v1）混入了已废弃的 xlsx 模块矩阵、Spring Boot 选项和海康视频方案，产出的评审不可用。
> 本版只包含**当前定稿**：方案 v1.1、14 条实机口径、2026-12-01 交付、真机 2026-11-10 直连。
>
> 用法：`scripts/run_model_review.py --prompt docs/model_review_prompt.md --image <参考图.png>`
> 参考图只发给豆包（GLM 的 `glm-5.2` 不收图）。

---

你是一位同时做过**工业物联网产品**和**全栈交付**的评审者。下面这份方案已经定稿、准备开工，现在是最后一道“泼冷水”的机会。

规则：

- 不要复述方案，不要客套，不要给“建议进一步调研”这种废话；
- 每条结论标注 **【事实】/【判断】/【未验证】**；
- 明确区分“必须现在改”和“知道了但不用改”；
- 如果你认为某处是过度设计，直接说砍掉，并说砍了会失去什么。

## 一、项目事实（全部已核实）

**机器人**：轮式防爆机器人，JCROB 视觉/雷达导航系统，HTTP 3546 + `/api/v1`，WS 3547，UDP 22002 发现。机器人自己做 SLAM、定位、路径规划、避障，平台不做 SLAM。

**关键接口事实**（PDF 109 页，逐页核过）：

- `/system/status` → `Mapping/Navigating/Busy/Free`
- `/system/info` → `battery`(%)、`camera_rgb/depth/odom/imu`(topic 频率 Hz)、`driver_port`(硬件急停，true=按下)、`charge`、`loop`、`info{version,code_name,id,mac,port}`、`slam_type`
- `/system/galileo_status` → 导航/视觉/建图/充电/循环状态、`power`(V)、目标点、`currentSpeedX/Theta`、`currentPosX/Y`、`currentAngle`、`busyStatus`
- 地图：`/navigation/saved_maps` 只返回 `resolution/origin/md5sum/map_type/levels/slam_type`（**没有 width/height**）；`/navigation/map_png?name=` 返回 PNG；换算 `x_map=x0+px*res`、`y_map=y0+h*res-py*res`，`h` 要自己读 PNG 像素高
- 位姿：`/navigation/pose` 与 `/map/pose` 的 `angle` 是**度**；`nav_action.theta` 是**弧度**；`currentAngle` 单位 PDF 未标
- 任务：`/task`（GET/POST/PUT/DELETE），状态 `WAITTING/WORKING/PAUSED/CANCELLED/ERROR/COMPLETE`；`/task/start|pause|resume|stop` 全是 GET，`stop` 不带 id 会取消**所有**任务
- `sub_tasks` 支持内联 action 对象，也支持嵌套行为树（`sequence/parallel/retry_until_success` 等，PDF p101–105）
- 动作：`nav/sleep/image/tts/callback/charge/local_move/io/switch_map/blockly/onvif…`
- WS：`/galileo/status`、`/bw_env_sensors/EnvSensorData`(temperature/rh/smoke/pm1_0/pm2_5/pm10/lel/noise)、`/bw_env_sensors/AirSensorData`(co2/illuminance)；每秒要发 `ping`，否则可能被断开
- 认证：`GET /token?username=&password=`，无 TTL、无 refresh、无失效返回体示例；`no_token_check` 语义在 PDF 里自相矛盾
- 没有：结构化告警接口、BMS 单体电压、AI 识别结果、MQTT、软件急停、多机器人调度

**约束**：

- 单人开发，**2026-12-01 交付**（今天 10/20，六周）；
- 真机 **2026-11-10** 才能直连，之前只能用 PDF 示例造 Mock；
- 部署在一台共享 Ubuntu 22.04 服务器（已跑着 52 个容器：CVAT/Dify/Postgres/MySQL/各种模型服务），我们只能用空闲端口 8099，资源要加前缀；
- 纯内网，将来可能上公网；
- 机器人电池供电，不做 7×24 运行和录像。

## 二、定稿方案（v1.1）

**技术栈**：Vue 3 + TS + Vite + Arco Design Vue + Pinia + ECharts + Canvas 自绘地图（不用 Leaflet）；FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic + MySQL 8；JWT(httpOnly Cookie)+CSRF；Docker Compose 三容器（server/mysql/nginx）；`uvicorn --workers 1`，后台任务用进程内 asyncio（`status_poller` 1s、`task_reconciler` 2s、`ws_listener` 长连接、`retention_job` 每日）。

**为什么单进程**：状态缓存、WS 连接、后台循环都在进程内，避免为单机器人引入 Redis。代价：只能单 worker，要多副本必须先把后台任务拆出去。

**本期做**：驾驶舱（状态/电量/急停/充电/位姿/速度/环境 WS）、地图与点位（PNG 底图、坐标换算、点位 CRUD、路径、虚拟墙/忽略区）、任务（模板、下发、暂停/继续/停止、执行记录、对账）、告警（阈值规则 + 平台推导）、历史/导出、审计、基础 RBAC。

**本期不做**：视频/云台/测温（后续）、BMS、AI 识别、MQTT/GB28181、软件急停、多机器人、7×24 录像。

**14 条实机口径**（已定）：

1. URL 按 PDF 原文，`move to index` 的空格编码为 `%20`，不做规范化；只有 404/405 才启用兼容别名；
2. `get_config` 白名单脱敏只读（`wifi_password` 等不落盘、不过前端）；
3. `/system/is_online` 只表示“机器人能否上互联网”，不是平台在线判定；
4. token 事件驱动（启动取一次 + 401/403 重取），不做定时轮换；
5. `currentAngle` 用多帧圆周误差判定单位，不用单帧比值；
6. `busyStatus=true` 不放宽写闸门（仍要求 `/system/status == Free` 且 `busyStatus == false`）；
7. “停止”默认带 `jcrob_task_id`，“取消全部”单列危险操作；
8. 机器人回调用 URL 里的 run token（PDF 只允许填 url/method/data，签不了 HMAC）；
9. 嵌套行为树：平台只产出扁平 action，读取必须容错，解析不了就保留原始 JSON 降级只读；
10. `progress` 单位未知，UI 不显示百分比进度条；
11. 写操作闸门：一个运动任务、二次确认、后端权限、3s 超时、不自动重试、成功 500ms 后重读状态；
12. 告警阈值未配置就不求值，显示“未标定”，不拿占位值冒充；
13. 地图数据超 3s 未更新，箭头变灰 + “数据过期”；
14. 所有写操作进 `operation_log`，第一次下发运动指令前需要现场负责人签字授权。

**数据量估算**（我自己的算，请核）：状态 1s 采样 → 8.64 万行/天 → 7 天约 60 万行；1 分钟聚合 180 天约 26 万行；环境 5s 降采样 → 1.7 万行/天 → 90 天约 156 万行。全部放 MySQL 单表，不做分区。

## 三、参考图（只发给豆包）

随附一张 PPT 截图，是**之前给客户/领导看过的“三维可视化巡检管理平台”示意**：3D 场站模型、设备告警气泡、左下角可见光/红外双画面、右下角机器人状态（电池温度/运行速度/电池电量）和历史告警列表。

这个方向**因为涉及三维建模被砍掉了**，本期不做 3D、不做视频。这张图只作为“审美与信息密度”的参考。

## 四、请回答

### A. 产品经理视角

1. 12/01 这场演示的**观众是谁、他真正想看什么**？按“一定会被问到的三个问题”给清单。
2. 参考图那个 3D 观感 vs 我们的 2D 底图 + 数据叠加，**落差该怎么管理**？不建模的前提下，有哪些低成本手段能把“像一个平台”的感觉补回来（具体到组件级）？
3. 参考图里那些我们本期不做的东西（视频、红外、3D、设备控制），在 UI 上应该**怎么显示才不显得残缺**？“未接入”的呈现方式给出 2–3 种取舍。
4. 交付验收 13 条（登录 2s 内看到状态、3 点位姿一致、3 点任务能跑、告警可产生/确认/导出、拔网线显示失联、不支持接口不弹成功、Mock 不进生产……）里，哪几条**客户大概率不认**、需要提前改口径？
5. 如果只有 30 分钟演示时间，**先演什么、后演什么、坚决不演什么**？

### B. 全栈工程师视角

1. 单进程 asyncio + 单 worker 的风险点在哪？给出“什么时候必须拆”的具体触发条件（并发数、任务数、延迟）。
2. 1s HTTP 轮询 + WS 推送双源的**一致性问题**：位姿到底以谁为准，时间戳怎么对齐，UI 抖动怎么处理？
3. Canvas 自绘地图（PNG 底图 + 缩放 + 点位 + 轨迹 + 虚拟墙）：单页 200 个点位、2000 个轨迹点的性能与交互（拖拽/缩放/拾取坐标），有哪些必踩的坑？
4. 任务状态机与 2s 对账：机器人是唯一真相源、平台库是镜像，这套设计在**丢包/超时/机器人重启**下会怎么坏？幂等键怎么设计？
5. 把 1s 状态采样放进 MySQL 单表、不做分区，7 天 60 万行，**真的够用吗**？什么时候会崩？给一个更省钱但不过度的方案。
6. 部署在已经有 52 个容器、load 平均 28 的共享服务器上，**我们的三个容器会遇到什么实际风险**？端口、磁盘、内存、Docker 网络、镜像拉取、备份冲突。
7. 六周排期（W1 骨架+只读 Adapter，W2 驾驶舱，W3 地图点位，W4 任务状态机，W5 告警历史审计，W6 联调部署）**关键路径在哪**？哪一周最容易爆？
8. 安全：JWT + CSRF + 机器 token 落库加密 + 回调 run token，这套在**纯内网**环境下是否过度？哪里还不够（比如机器 token 明文进日志、回调伪造、审计缺人）？

### C. 两者都要回答

1. 这份方案里**最值得质疑的 3 个假设**是什么？
2. 如果只能保留 5 个页面，留哪 5 个？
3. 哪里是**过度设计**，砍了会失去什么？
4. 12/01 之前，**最可能翻车的单点**是什么，怎么提前三天发现它？

## 输出格式

- A. 结论先行（≤10 行，必须包含“建议现在改的 N 件事”）
- B. 产品经理视角（对应 A1–A5）
- C. 全栈工程师视角（对应 B1–B8）
- D. 共同问题（C1–C4）
- E. 与我方结论冲突的地方（明确列出“我认为你错了，因为……”）
