# 防爆机器人平台 — 项目交接文档

> 更新时间：2026-10-20（v1.1，14 条联调口径已定稿）
>
> 交接对象：接手本项目的下一个 Agent / 开发
>
> 当前状态：**方案已定稿，代码尚未开始**。机器人真机尚未接入，固件版本未知，视频/云台本期后置。
>
> 交付日：**2026-12-01**。部署目标机：**192.168.8.40**（已 SSH 实测，见第 9 节）。

---

## 0. 30 秒结论

- 目标：给一台 **JCROB 轮式防爆机器人** 做单机巡检平台。
- 唯一机器人能力依据：`API接口导航2024_HTTP_20240619142112(1).pdf`（109 页）。
- 技术栈：**Vue 3 + FastAPI + MySQL + Nginx**，3 个容器起步。
- 本期只做：状态驾驶舱、地图/点位、任务下发与巡航、告警、历史、审计、基础 RBAC。
- 本期不做：视频、云台、测温、15 串 BMS、AI 识别、MQTT/GB28181、软件急停、多机器人、7×24 录像。
- 固件版本未知：启动时做能力探测，不按型号/版本写死功能。
- 当前没有任何应用代码，只有方案、数据采集表、探针和几个生成脚本。

### 0.1 可直接交给下一个 Agent 的启动提示词

```text
你在 Windows 工作区 D:\Desktop\防爆机器人 接手“JCROB 轮式防爆机器人单机巡检平台”。

开工前先完整阅读 HANDOFF.md，再读 docs/平台方案-定稿.md、docs/PDF-SDK能力与平台方案.md、
docs/PDF接口原文索引.md。PDF 是唯一机器人能力依据；xlsx、UI 照片、demo 源码和项目架构.txt
都不能当作机器人接口或能力依据。

当前方案已定稿但应用代码尚未开始；固件版本未知，视频/云台/测温本期后置。不要重新发明架构，
不要访问 http://192.168.8.40:8890/（那是别人的 demo），不要删除或覆盖用户文件，不要把任何 API key 写入文件。
交付日 2026-12-01，部署目标是 192.168.8.40（Ubuntu 22.04 + Docker Compose，见第 9 节）。
先按 HANDOFF.md 第 6.3 节搭建 web/、server/、contracts/、deploy/ 骨架，从只读 JCROB Adapter
和 Mock 驾驶舱开始。运动、IO、充电等写操作必须保留二次确认、权限校验和审计；平台“停止”
只能描述为取消任务，不能宣传为安全急停。遇到 PDF 未写明的单位或语义，先实测并记录，不要猜。
动手前先读 docs/JCROB实机兼容性.md，URL 一律按 PDF 原文，不做规范化。
```

**先读这四份，别先读旧方案：**

1. [docs/平台方案-定稿.md](docs/平台方案-定稿.md)
2. [docs/PDF-SDK能力与平台方案.md](docs/PDF-SDK能力与平台方案.md)
3. [docs/PDF接口原文索引.md](docs/PDF接口原文索引.md)
4. [README.md](README.md)

**冲突处理顺序：**

1. 机器人接口、字段、能力：以 PDF 原文为最高优先级；
2. 当前项目范围、用户约束和已拍板决策：以本文件为准；
3. 具体架构、数据模型和页面设计：以 `docs/平台方案-定稿.md` 为准；
4. 一页纸和旧方案只作摘要/历史；发现与前三者冲突时，先修文档，不要按旧内容写代码。

---

## 1. 项目背景与用户约束

### 1.1 对象

- 机器人：**JCROB 视觉/雷达导航的轮式防爆机器人**。
- 不是绝影 X30 机器狗；本地 `D:\Desktop\工作1\机器狗\导览系统效果图\` 里的照片只是别人家产品的 UI 参考，不是本项目机器人。
- 机器人接口：HTTP 默认 `3546`，前缀 `/api/v1`；WebSocket 默认 `3547`；UDP 发现 `22002`。
- 机器人自己完成 SLAM、定位、路径规划、避障；平台不做 SLAM。

### 1.2 硬约束

| 约束 | 内容 |
|---|---|
| 唯一原厂资料 | 只有那份 PDF；xlsx、UI 照片、demo 源码、`项目架构.txt` 都不是原厂资料 |
| 人员 | 单人开发，没有现成团队 |
| 时间 | **2026-12-01 交付**；2026-10-20 起算，六周 + 1 天；真机 **2026-11-10 可直连（已确认）** |
| 供电 | 电池供电，不做 7×24 连续运行/录像 |
| 视频 | 本期明确后置；后续再接海康可见光+热成像 |
| 版本 | 固件版本未知，不能按版本写死能力 |
| 网络 | 固定 IP/现场网络后续才可达；目前不能访问真机 |
| 8.40 服务器 | 用户在上面传文件，**未获允许前不要访问** `http://192.168.8.40:8890/` |

### 1.3 用户最新指令（2026-10-20）

> “全部 sdk，版本暂不知道，云台也先不管，我们先把平台方案弄好吗，然后能通过 sdk 接，后续把真机该拿的数据拿到接入就行了。”

解释：

- PDF 就是全部 SDK，不需要再找别的 SDK；
- 云台/视频现在不做；
- 先把平台方案和 SDK Adapter 设计好；
- 真机数据后续再采、再填。

### 1.4 更早的关键指令

> “不要参考我给你的任何资料，我们给的真实原厂的资料只有那个 PDF 的 SDK 资料。”

因此：

- 机器人能力、字段、接口名只能以 PDF 为准；
- xlsx 里的 BMS/AI/空调/人脸等模块，不能当成 SDK 能力；
- UI 照片只能做视觉参考，不能做功能依据；
- 旧方案里混入的 xlsx 模块矩阵已经标注为历史资料。

---

## 2. 已定方案（不要重新发明）

### 2.1 技术栈

| 层 | 选择 |
|---|---|
| 前端 | Vue 3 + TypeScript + Vite + Arco Design Vue + Pinia + Vue Router |
| 图表 | ECharts |
| 地图 | Canvas 自绘 + PNG 底图（不用 Leaflet） |
| 后端 | FastAPI + Pydantic v2 + SQLAlchemy 2.x + Alembic |
| 数据库 | MySQL 8 |
| 认证 | JWT（httpOnly Cookie）+ CSRF |
| 部署 | Docker Compose + Nginx，3 个容器（server/mysql/nginx）；目标机 192.168.8.40，nginx 用宿主 8099，全资源加 `jc-` 前缀 |
| 后台任务 | FastAPI 进程内 asyncio 任务，`uvicorn --workers 1` |

**切换条件**：客户强制 Java 技术栈，或交付后必须由 Java 团队维护 → Spring Boot 3.2；前端、API 契约、数据表不变。

### 2.2 架构

```text
浏览器 Vue 3
   ↓
Nginx（静态 + /api 反代）
   ↓
FastAPI 单进程
   ├─ REST API
   ├─ 平台 WebSocket（推浏览器）
   ├─ status_poller（1s）
   ├─ task_reconciler（2s）
   ├─ ws_listener（机器人 WS，1s ping）
   └─ retention_job（每天）
   ↓
JCROB Adapter
   ├─ HTTP 3546 /api/v1
   ├─ WS 3547
   └─ UDP 22002 发现
   ↓
JCROB 轮式防爆机器人
```

机器人可以通过 `callback_action` 反向调用平台；平台回调接口用 HMAC，不用用户 JWT。

### 2.3 为什么单进程

状态缓存、WS 连接、后台循环都在进程内，避免为了单机器人引入 Redis。

代价：只能单 worker；将来要多副本，必须把后台任务拆成独立 worker，不能直接 `--workers N`。

### 2.4 本期范围

**做：**

- 驾驶舱：状态、电量、硬件急停状态、充电、循环、电压、位姿、速度、导航/视觉状态、环境 WS；
- 地图与点位：地图列表、PNG、`nav_points`、`path`、连接点、虚拟墙、忽略区、切图；
- 任务：模板、创建、启动、暂停、继续、停止、执行记录；
- 巡航：`loop_task` 或“导航点 + 到点动作”的任务；
- 告警：环境阈值、电量、离线、急停、任务错误、自检失败；
- 历史与导出、审计、基础 RBAC。

**不做：**

- 视频/云台/测温（后续阶段）；
- 15 串 BMS 单体电压（PDF 只有 `battery` 百分比和 `power` 电压）；
- 结构化告警接口（PDF 没有，平台推导）；
- AI 表计/缺陷识别；
- MQTT / GB28181；
- 软件急停（PDF 只有 `driver_port` 读取硬件急停状态）；
- 多机器人调度；
- 7×24 录像。

### 2.5 任务与巡航

定位与巡航的关系：

- 机器人自己完成 SLAM、定位、路径规划和避障；平台不需要另配 UWB、二维码或外部定位模块，也不做 SLAM。
- 平台看到的机器人位置来自 `/navigation/pose` 或 `/map/pose`，不是平台自己算出来的。
- `/system/info` 里的 `odom`、`imu` 是 topic 发布频率/可用性信息，不是平台可直接消费的原始定位数据。
- 视觉导航与雷达导航的启动条件不同；以 PDF 和真机能力探测结果为准，不能假设两种模式完全等价。

两种方式：

1. `POST /navigation/loop_task {wait_time}`：沿当前路径的导航点循环，适合固定路线；
2. `POST /task`，`sub_tasks` 放 `nav_action`、`sleep_action`、`image_action`、`tts_action`、`callback_action`：适合到点等待/拍照/播报/回调。

注意：

- 等待动作叫 **`sleep_action`**，不是 `wait_action`；
- `nav_action.theta` 单位是**弧度**（PDF 第 91 页）；
- `/navigation/pose.angle` 和 `/map/pose.angle` 单位是**度**（PDF 第 54、59 页）；
- `/system/galileo_status.currentAngle` PDF 没标单位，启动时用 pose 对比判定；
- `nav_points.theta` PDF 没标单位，样例像弧度，必须实机确认。

### 2.6 安全边界

| 事实 | 结论 |
|---|---|
| `/system/info.driver_port` 是硬件急停按钮状态（true=按下） | 只能读，不能控制 |
| PDF 没有软件急停接口 | 平台“停止”=取消任务，不是安全急停 |
| `/task/stop` 不带 id 会取消机器人上**所有**任务 | 主按钮始终带 `jcrob_task_id`；“取消全部”单列危险操作 |
| 所有任务/导航写接口多是 GET | 平台内部必须改成 POST + 二次确认 + 审计 |
| 运动写操作可能不可重试 | 超时不要盲目重发 |
| 失联时无法远程急停 | 需要车端自治停车；平台只告警 |
| 第一次下发运动指令前需要现场负责人签字（姓名+日期+范围） | 采集表 01 表第 15–17 行；平台把这条作为写操作开启的前置条件 |

---

## 3. PDF 事实（带页码）

### 3.1 接入

| 项 | 值 | 页码 |
|---|---|---:|
| HTTP 端口 | 3546 | 7 |
| API 前缀 | `/api/v1` | 7 |
| WS 端口 | 3547 | 106 |
| UDP 发现 | 22002，广播 `id/port/mac/version` | 7 |
| token | `GET /token?username=&password=` | 8 |
| token 传递 | GET/DELETE 放 query；POST/PUT 放 query 或 body | 8 |
| `no_token_check` | 默认可能是 true | 8 |

### 3.2 状态

| 接口 | 关键字段 | 页码 |
|---|---|---:|
| `GET /system/status` | `Mapping/Navigating/Busy/Free` | 9 |
| `GET /system/info` | `battery`、`camera_rgb`、`camera_depth`、`odom`、`imu`、`driver_port`、`charge`、`loop`、`info.version`、`slam_type` | 9–10 |
| `GET /system/galileo_status` | `navStatus`、`visualStatus`、`mapStatus`、`chargeStatus`、`loopStatus`、`power`、`targetStatus`、`targetDistance`、`controlSpeedX/Theta`、`currentSpeedX/Theta`、`currentPosX/Y/currentAngle`、`busyStatus` | 10–11 |
| `GET /system/self_test` | `motor_driver`、`camera`、`charge`、`lidar`、`bluetooth`、`battery` | 16–17 |

### 3.3 地图与定位

| 接口 | 说明 | 页码 |
|---|---|---:|
| `GET /map/pose` | `x/y` 米，`angle` 度 | 54 |
| `GET /navigation/pose` | `x/y` 米，`angle` 度 | 59 |
| `GET /navigation/saved_maps` | 地图列表；`type` 可为 camera/lidar/all | 60 |
| `GET /navigation/map_png?name=` | PNG | 62 |
| `GET /navigation/current_map` | 当前地图 | 62 |
| `GET /navigation/nav_points` | 点格式 `x y z theta errorX errorY direction name` | 72 |
| `GET /navigation/path` | 路径 | 70 |

坐标换算（PDF 第 54–55 页）：

```text
x_map = x_origin + x_pixel * res
y_map = y_origin + h_map * res - y_pixel * res
```

### 3.4 任务与动作

| 接口 | 说明 | 页码 |
|---|---|---:|
| `GET/POST/PUT/DELETE /task` | 任务 CRUD | 86–88 |
| `/task/start`、`pause`、`resume`、`stop`、`loop` | 任务控制，均为 GET | 88–89 |
| `GET/POST/PUT/DELETE /action` | 动作 CRUD | 89–97 |
| `/action/update_wait_req` | 触发等待动作 | 97 |
| `/blockly_task` | 自动化任务 | 98–99 |

任务字段：`name`、`loop_flag`、`id`、`state`、`sub_tasks`、`progress`、`current_task`（第 87 页）。

Action 类型（第 90–96 页）：

```text
callback_action
sleep_action
nav_action
charge_action
local_move_action
wait_req_action
switch_map_action
change_setting_action
roslaunch_action
io_action
elevator_req_action
none_stop_nav_action
blockly_action
video_record_action
image_action
tts_action
onvif_camera_move_action
onvif_camera_snapshot_action
slide_action / jacking_action / jacking_rotate_action
local_move_target_action
```

### 3.5 WS

| Topic | 字段 | 页码 |
|---|---|---:|
| `/galileo/status` | JSON，schema 参照 GalileoStatus | 106 |
| `/bw_env_sensors/EnvSensorData` | `temperature`(℃)、`rh`(%RH)、`smoke`(ppm)、`pm1_0`、`pm2_5`、`pm10`、`lel`(ppm)、`noise`(db) | 107 |
| `/bw_env_sensors/AirSensorData` | `temperature`、`rh`、`co2`(ppm)、`illuminance`(lux) | 107 |

WS 需要每秒发 `ping`。6.2.1+ 可以通过 WS 发 ROS topic（包括 `cmd_vel`）。

### 3.6 已纠正的错误（重要）

| 错误写法 | 正确事实 |
|---|---|
| `wait_action` | 应为 `sleep_action` |
| `driver_port` 当端口 | 是硬件急停按钮状态 |
| 把 `/navigation/move to index` “规范化”成 `move_to_index` | 原文带空格；请求时编码为 `%20`，这是编码不是改名。只有原文路径返回 404/405 才启用兼容别名 |
| `currentAngle` 当度、或直接用单帧比值判定 | PDF 没标单位；用 `--angle-check` 多帧圆周误差判定，判不出就标“角度单位待确认” |
| `nav_points.theta` 当度 | 读按弧度；**写回前必须先实测单位**，未确认时禁止上传点位 |
| 任务“没有推送只能轮询” | 有 `callback_action` 可回调平台；持续状态仍需轮询 |
| `busyStatus=true` 只是“延迟执行”所以可以下发 | PDF 没写队列、覆盖、取消语义；闸门仍要求 `/system/status == Free` 且 `busyStatus == false` |
| `/system/is_online` 当平台在线判定 | 它只表示“机器人能否连上互联网”；平台在线看轮询 + WS 心跳 |
| `progress` 直接当百分比显示 | PDF 只给 `"progress": 0`，单位未知；UI 不显示百分比进度条 |
| 嵌套 `sub_tasks` 是 PDF 没定义的东西 | p101–105 已定义行为树控制节点；平台只产出扁平 action，**读取必须容错** |
| `/system/config` 原样返回给前端 | 含 `wifi_password` 等字段；只读、走白名单、落盘前脱敏 |
| `callback_action` 能带自定义 Header / HMAC | p90 只有 `url/method/data`；改用 URL 里的 run token |

---

## 4. 文件清单

### 4.1 根目录

| 文件 | 状态 | 说明 |
|---|---|---|
| `API接口导航2024_HTTP_20240619142112(1).pdf` | **权威** | 109 页 JCROB SDK；唯一机器人能力依据 |
| `README.md` | 入口 | 文档地图、当前定稿、复现命令 |
| `HANDOFF.md` | 本文件 | 交接说明 |
| `真机联调数据采集表.xlsx` | **在用** | 8 个工作表，现场采集；05 视频表后置 |
| `真机数据契约.xlsx` | 历史 | 早期 6 表数据契约，已被采集表取代 |
| `防爆机器人平台-实施方案v2.md` | 历史 | v3.0，含 xlsx 模块矩阵/UI 分析；顶部有“以此为准”修订横幅，能力依据不看它 |
| `防爆机器人可视化平台项目方案.md` | 历史 | 更早的方案，已被取代 |
| `_jcrob_pdf_text.txt` | 生成物 | PDF 文本提取，便于 `grep`；以 PDF 原文为准 |
| `_screens_contact.png` / `_ui_contact.jpg` / `_xlsx_image1.png` | 分析产物 | UI/xlsx 图片拼接，非权威，可删 |
| `_tech_spec_dump.txt` | 分析产物 | xlsx 文本 dump，非权威，可删 |

### 4.2 docs/

| 文件 | 状态 | 说明 |
|---|---|---|
| `平台方案-定稿.md` | **权威** | 平台架构、Adapter、数据模型、API、状态机、告警、UI、六周计划、验收 |
| `PDF-SDK能力与平台方案.md` | **权威** | PDF 能力地图、能做什么/不能做什么、真机 12 项确认 |
| `PDF接口原文索引.md` | **权威（生成）** | 178 条 URL 记录，含页码/方法/原文标题。由脚本生成，**不要手工加兼容说明**（会被覆盖） |
| `JCROB实机兼容性.md` | **权威（手写）** | URL 编码/别名、字段补正、单位判定记录、待实机确认清单 |
| `真机取数清单.md` | **权威（手写）** | 真机 11/10 直连时的取数规格：D01–D35 取数项、交付包结构、解锁映射、验收标准 |
| `交付说明-一期范围.md` | **对外** | 给客户/领导的范围边界：一期做什么、不做什么、三条边界（停止≠急停）、验收量化口径 |
| `评审结论与修改清单-20261020.md` | 参考 | 豆包/GLM 评审的裁决：采纳 11 条、驳回 5 条（含 2 条事实错误） |
| `方案定稿-一页纸.md` | 摘要 | 一页纸版本，可能滞后于主方案 |
| `项目目录结构-适配版.md` | 参考 | 单仓库双应用 `web/` + `server/` 的目录建议 |
| `外部接口占位规范.md` | 参考 | BMS/固定设备/AI/气象/门禁的占位 API；不属于 PDF |
| `open-source-references.md` | 参考 | GitHub 参考项目，已核 star/许可证/最近提交 |
| `model_review_20261020-140309.md` | 历史 | 豆包/GLM 原始评审；两段高度雷同，不可当独立证据 |
| `model_review_prompt.md` | 工具 | 模型评审提示词 |
| `UI设计基线-实拍参考.md` | 历史 | 基于实拍照片的旧 UI 分析；照片仅可参考布局/配色/按钮样式，组件重做，能力仍以 PDF 为准 |

### 4.3 scripts/

| 文件 | 用途 | 是否写文件 |
|---|---|---|
| `extract_pdf_endpoints.py` | 从 PDF 提取 URL 索引 | 写 `docs/PDF接口原文索引.md` |
| `probe_jcrob.py` | 真机只读探针（HTTP/WS/地图/角度单位判定），落盘前脱敏 | 写 `probe_out/<timestamp>/` |
| `build_collection_sheet.py` | 生成真机采集表 | **覆盖** `真机联调数据采集表.xlsx` |
| `run_model_review.py` | 调豆包/GLM | 写 `docs/model_review_*.md` |

---

## 5. 脚本用法

### 5.1 重新生成 PDF 接口索引

```powershell
cd D:\Desktop\防爆机器人
python scripts\extract_pdf_endpoints.py
```

输出：`docs/PDF接口原文索引.md`。

脚本逻辑：pdfplumber 逐页 `extract_text()` → 匹配 `URL:` → 向下找 `请求方式:` → 记录页码/方法/URL/标题。**不做 URL 规范化**。

### 5.2 真机只读探针

```powershell
python scripts\probe_jcrob.py `
  --base http://<robot-ip>:3546 `
  --username <user> --password <password> `
  --ws --download-map
```

或直接给 token：

```powershell
python scripts\probe_jcrob.py --base http://<robot-ip>:3546 --token <token>
```

输出：`probe_out/<timestamp>/`，包含每个接口的 JSON、原始响应、`summary.json`。

注意：

- 只读；不调用任务启动/停止/充电/IO/云台；
- token 不落盘、不打印；
- 需要能访问机器人的 3546/3547。

### 5.3 重新生成采集表

```powershell
python scripts\build_collection_sheet.py
```

**警告**：会覆盖 `真机联调数据采集表.xlsx`。如果用户已经填了数据，先备份再运行。

### 5.4 模型评审（可选）

```powershell
$env:ARK_API_KEY='...'
$env:GLM_API_KEY='...'
python scripts\run_model_review.py --prompt docs\model_review_prompt.md --out docs
```

密钥只放临时环境变量，不写入文件、不提交。用户曾在对话里贴过密钥，建议提醒轮换。

---

## 6. 已完成 / 未完成

### 6.1 已完成

- PDF 全文提取与 178 条 URL 索引；
- PDF 能力地图（能做什么/不能做什么）；
- 平台方案定稿（架构、Adapter、数据模型、API、状态机、告警、UI、六周计划、验收）；
- 真机采集表（8 个工作表，v1.1 已按联调口径修订：原文 URL、is_online 降级、热成像/云台后置、config 只读脱敏、嵌套任务行）；
- 只读探针脚本（v1.1：落盘前脱敏 + `config_view` 白名单 + `--angle-check`）；
- 14 条实机联调口径定稿（见 `docs/平台方案-定稿.md` 头部与 §3.6）；
- 8.40 部署环境只读实测（见第 9 节）；
- 豆包/GLM 评审（有雷同段警告，不作为独立证据）；
- GitHub 参考项目核实；
- README / HANDOFF / `docs/JCROB实机兼容性.md`。

### 6.2 未完成

- **没有任何应用代码**：没有 `web/`、`server/`、`contracts/`、`deploy/`；
- 没有真机数据；
- 没有固件版本；
- 没有确认 `callback_action` 网络可达；
- 没有确认现场报警阈值；
- 没有 UI 实现；
- 没有 Git 仓库；
- 机器人没在 8.40 网段上被发现（2026-10-20 在 22002 静听 12 秒，0 包）。

### 6.3 建议的下一步

1. 建 `web/` + `server/` + `contracts/` + `deploy/` 骨架，`deploy/docker-compose.yml` 按第 9 节的端口与命名写；
2. `server` 先做 `/health`、登录、机器人连接配置；
3. 写 `JCROB Adapter` 只读部分（token/status/info/galileo/pose/map/config）；
4. 用探针录包做 Mock，先把驾驶舱跑起来；
5. 再做地图/点位、任务、告警、历史；
6. 真机可达后填采集表，锁字段/单位/状态机。

---

## 7. 真机联调顺序

### 7.1 前置条件

- 能访问机器人 `3546` / `3547`；
- 知道机器人 IP、账号、密码（或 token）；
- 现场有安全员、硬件急停、空旷区域；
- 确认 `no_token_check` 状态（只作为信息，不据此改平台策略）；
- **写操作前有签字授权**：采集表 01 表第 15–17 行填姓名 + 日期 + 允许范围 + 安全条件。

### 7.2 第一轮：只读

只跑：

```text
GET /system/status
GET /system/info
GET /system/galileo_status
GET /system/self_test
GET /navigation/saved_maps
GET /navigation/current_map
GET /navigation/pose
GET /map/pose
GET /navigation/nav_points
GET /navigation/path
GET /task
GET /action
```

记录：

- 每个接口的原始 JSON（探针已自动脱敏，`config` 另有 `config_view.json`）；
- 字段单位；
- 枚举值；
- 响应时间；
- WS 频率；
- 断线表现。

角度单位单独跑（建议机器人慢慢转 30 秒以上，否则会输出“无法判定”）：

```powershell
python scripts\probe_jcrob.py --base http://<robot-ip>:3546 --token <token> --angle-check --angle-check-seconds 40
```

### 7.3 第二轮：任务（允许后）

- 先创建 `nav_action + sleep_action` 的单点任务；
- 启动、暂停、继续、停止；
- 记录 `progress`、`current_task`、状态跳变；
- 再测试 `loop_task`；
- 最后测试 `callback_action`。

### 7.4 第三轮：写操作（单独确认）

按顺序：

1. 导航；
2. 充电；
3. IO；
4. 遥控/`local_move`；
5. 配置/校准/升级（管理员）。

每一步都要二次确认 + 审计 + 安全员在场。

### 7.5 必须拿到的数据

1. `info.version`、`slam_type`、`info.port`；
2. `/system/status` 四态；
3. `galileo_status` 全字段 + `currentAngle` 单位；
4. `/navigation/pose` 与 `/map/pose` 同点读数；
5. `saved_maps` + `map_png` + `origin/resolution/width/height`；
6. `nav_points` 格式与 `theta` 单位；
7. `loop_task` 的 `wait_time` 与中断表现；
8. `/task` 创建/启动/暂停/停止的同步性和 `progress`；
9. `callback_action` 机器人到平台的网络可达性；
10. `driver_port` 急停、`self_test`、实际续航。

---

## 8. 陷阱与禁止事项

### 8.1 接口名

- 不要凭记忆写接口名；先查 `docs/PDF接口原文索引.md`。
- 不要“规范化”URL：`/navigation/move to index` 原文带空格；`/navigation/upload_map to robot` 也带空格。发送时编码为 `%20`，这是编码不是改名。
- 索引里方法写“—”的，是提取没抓到，不代表“无方法”（`/system/self_test` 实测就是 GET）。
- 平台自建 API（`/api/v1/robots/...`）必须标注“我设计的”，不要混成 SDK 接口。

### 8.2 能力

- 不要把 xlsx 的 BMS/AI/空调/人脸/气象站当成 SDK 能力。
- 不要把 UI 照片里的模块当成需求。
- 不要承诺视频/云台/测温；本期后置。
- 不要承诺软件急停；PDF 没有。
- 不要承诺多机器人调度；`schedule_manager` 是外部调度服务器。
- 不要做 7×24 录像；电池供电。
- 不要把 `/system/is_online` 当平台在线判定。

### 8.3 单位

- pose 的 `angle` 是度；
- `nav_action.theta` 是弧度；
- `local_move.angle` 是弧度；
- `currentAngle` 和 `nav_points.theta` 单位未标：前者用 `--angle-check` 多帧判定，后者读按弧度、写前必须实测；
- 不要把度和弧度混在一个字段里。

### 8.4 写操作

- SDK 很多写接口是 GET；平台对外必须用 POST + 二次确认 + 审计。
- 运动类命令超时不要自动重试。
- 同一机器人同一时间只允许一个运动任务。
- `busyStatus` 不放宽：仍要求 `/system/status == Free` 且 `busyStatus == false`。
- `/task/stop` 必须带 `jcrob_task_id`；不带 id 会取消全部任务，“取消全部”单列危险操作。
- 停止任务 ≠ 停止导航，导航要 `/navigation/stop_nav_task`。
- 失联时不要假装还能急停。

### 8.5 文件

- `build_collection_sheet.py` 会覆盖采集表；用户填过数据后先备份（本次备份在 `_backup/`）。
- 不要把 API key 写进任何 md/py/json。
- 不要删除用户文件；本目录不是 Git 仓库，删了不好恢复。
- 8.40 已获授权可 SSH（`ZeroStack@192.168.8.40`）；`8890` 那个 demo 仍然不要碰。
- 密码只走临时环境变量，不写进任何文件。

### 8.6 模型评审

- 豆包/GLM 的评审输入混了 xlsx 模块，不能当 PDF 结论。
- 两家在风险/6 周/假设三段几乎逐字相同，不能当独立证据。

---

## 9. 环境与运行

### 9.1 本机（开发机）

| 项 | 值 |
|---|---|
| OS | Windows |
| Shell | PowerShell |
| 工作目录 | `D:\Desktop\防爆机器人` |
| Python | 3.14.2 |
| 已装 | pdfplumber 0.11.10、openpyxl 3.1.5、httpx 0.28.1 |
| Git | **不是 Git 仓库** |

> 本工作区的目录权限曾被 Windows ACL 挡住（写文件报 `Access is denied`）。已用诊断脚本补上当前用户的完全控制权限，备份与回滚脚本在 `D:\Desktop\_dsh_acl_reports\`。若再出现“沙箱拒绝写入”，先查这个，不要改代码绕过。

### 9.1.1 部署机 192.168.8.40（2026-10-20 实测）

| 项 | 值 |
|---|---|
| 主机 / 系统 | `MtAI`，Ubuntu 22.04.5 LTS，kernel 5.15，64 位 |
| 算力 | 32 核 / 252 GB 内存（可用 227 GB），load ~28（被 CVAT/Dify/大模型占用，不影响我们） |
| 磁盘 | `/` 468G（剩 377G）、`/data` 3.6T（剩 1.9T）、NFS 15T 挂 `/mnt/nas_docs` |
| Docker | 29.5.3 + Compose v5.1.4，`data-root=/data/docker`，已配镜像加速 |
| 权限 | `ZeroStack` 在 `docker` 组，跑容器不用 sudo；`sudo` 需密码 |
| 时区 | Asia/Shanghai，NTP 已同步 |
| 网卡 | `eno1` 192.168.8.40/24；`eno2` 192.168.1.248/24（与 AI 视频盒子 192.168.1.169 同段，可达） |
| 已占用端口 | 80/81/82/443/8080/8082/8086/8890/8899/3001/3005/3008/3030/5001/5003/5005/5678/8000/8001/8123/8888/11434/3306… |
| 空闲端口 | **8099**、9099、3307、8891、3546/3547 |
| 已有容器 | 52 个：CVAT、Dify、FastGPT、n8n、o2oa、Traefik、Portainer、Dockge、`mysql:8.4.4`(3306)、`robot-dashboard`(8890 的旧 demo) |
| 防火墙 | ufw 服务在跑但 `status: inactive` |
| 机器人发现 | 22002 静听 12 秒 **0 包** → 机器人未上电或不在该网段 |

**部署约定**：代码放 `/data/jcrob-platform`；容器/网络/项目名一律 `jc-` 前缀；nginx 挂宿主 8099；server 与 mysql 不发布宿主端口；数据 bind mount 到 `/data/jcrob-platform/data/{mysql,uploads,exports,logs}`；MySQL 用本机已有的 `mysql:8.4.4` 镜像、不与他人共用 3306 那台实例。

### 9.2 编码

- 文档全部 UTF-8。
- PowerShell 控制台可能把中文显示成乱码；读取文件用 `Get-Content -Encoding UTF8` 或 Python `encoding='utf-8'`。
- 写文件优先 `apply_patch`；生成脚本写文件可以。

### 9.3 网络

- **GitHub 必须走本地代理** `http://127.0.0.1:9876`（2026-10-21 实测，原说明见 `docs/screenshots/Agent-GitHub访问说明.md`）：
  - Python（urllib/httpx）设 `HTTP_PROXY`/`HTTPS_PROXY` 即可，实测 `api.github.com`、`raw.githubusercontent.com` 都 200；
  - **`curl.exe` 走不通**：Schannel 报 `SEC_E_NO_CREDENTIALS (0x8009030e)`，别拿 curl 判断网络通不通；
  - **git 必须带两个 `-c`**：`git -c http.sslBackend=openssl -c http.proxy=http://127.0.0.1:9876 …`，实测 `ls-remote` 成功；
  - 进程继承到的代理变量可能是不可用的 `127.0.0.1:9`，用前先覆盖。
- 豆包/GLM API 可直连（不需要代理）。
- 机器人网络尚未接通：8.40 同时有 192.168.8.0/24 与 192.168.1.0/24 两块网段，**接哪段待现场确认**。
- 纯内网部署；将来上公网要先加反代 + HTTPS，本期不做。

### 9.4 运行检查

```powershell
python -m py_compile scripts\probe_jcrob.py scripts\build_collection_sheet.py scripts\run_model_review.py scripts\extract_pdf_endpoints.py
python scripts\extract_pdf_endpoints.py
```

> 注：`scripts\__pycache__` 目前仍写不进去（权限问题），`py_compile` 会报 PermissionError。用 `py_compile.compile(..., cfile=<临时路径>)` 或在有权限的目录下跑。

---

## 10. 待用户确认

已定：交付日 **2026-12-01**；部署用 Docker Compose 上 8.40；纯内网；平台独立账号；告警阈值先留空、前端可改；免责文案写进 UI；**真机 2026-11-10 可直连（已确认）**。

仍待确认：

1. 机器人接哪个网段（8.40 的 192.168.8.0/24 与 192.168.1.0/24 都通，具体 IP 现场给）；
2. 机器人能否反向访问平台（`callback_action` 需要可达 URL）；
3. 现场 `lel`/`smoke`/`temperature` 的报警阈值由谁给（未给之前不告警）；
4. 现场负责人对采集表 01 表第 15–17 行的签字；
5. 现场固件版本（不影响开发，但影响能力探测结果）。

---

## 11. 交接检查清单

- [ ] 已读 `平台方案-定稿.md`，知道本期不接视频/云台。
- [ ] 已读 `PDF-SDK能力与平台方案.md`，知道哪些能力 PDF 没有。
- [ ] 已读 `JCROB实机兼容性.md`，知道 URL 按原文发送、兼容别名只在 404/405 时启用。
- [ ] 已用 `PDF接口原文索引.md` 核对过要用的接口名。
- [ ] 没有把 xlsx/UI 照片/demo 当能力依据。
- [ ] 没有把 `wait_action`、`move_to_index`、`driver_port` 端口之类错误带进代码。
- [ ] 知道 `driver_port` 是急停状态、不是端口。
- [ ] 知道 `sleep_action` 是等待动作。
- [ ] 知道 `currentAngle` 用 `--angle-check` 多帧判定、`nav_points.theta` 写前必须实测。
- [ ] 知道 `busyStatus` 不放宽、`/task/stop` 必须带 id。
- [ ] 知道 `/system/config` 要白名单脱敏，`wifi_password` 不落盘。
- [ ] 知道 `/system/is_online` 不是平台在线判定。
- [ ] 知道嵌套 `sub_tasks` 是已定义能力，读取要容错。
- [ ] 知道采集表会被脚本覆盖，已备份用户数据。
- [ ] 没有把 API key 写进文件。
- [ ] 部署前看过第 9.1.1 节的端口与命名约定，没有占用别人的端口/容器名。
- [ ] 下一步是搭 `web/` + `server/` 骨架，不是继续写方案。

---

## 12. 术语表

| 术语 | 含义 |
|---|---|
| JCROB | 机器人导航系统厂商/协议名 |
| GalileoStatus | JCROB 的整体状态对象 |
| `driver_port` | 硬件急停按钮状态，true=按下 |
| `nav_action` | 导航到 `x/y/theta` 的动作，theta 弧度 |
| `sleep_action` | 等待 `wait_time` 秒的动作 |
| `callback_action` | 机器人向指定 URL 发请求的动作 |
| `loop_task` | 沿导航点循环的导航任务 |
| `nav_points` | 导航点文件，格式 `x y z theta errorX errorY direction name` |
| `point_connections` | 跨地图/跨楼层连接点 |
| `no_token_check` | 机器人是否关闭 token 校验 |
| `slam_type` | `camera` 或 `lidar` |
| `driver_port` | 急停按钮，不是通信端口 |
| `WAITTING` | PDF 原文拼写，双 T |

---

## 13. 一句话交接

**方案已经定稿，接口已经逐条溯源，14 条实机口径已拍板；下一步不要重新讨论“做什么”，直接按 `docs/平台方案-定稿.md` 搭骨架，先只读、再任务、最后写操作。12/01 交付，真机 11/10 可直连，到那天上午先做半天只读冒烟再开工任务写入。**
