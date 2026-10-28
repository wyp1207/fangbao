claude.exe : Claude Code doesn't recognize the model "deepseek-flash", so it assumes a context window of 200k tokens. U
pdate Claude Code, or see https://code.claude.com/docs/en/model-config#correct-the-window-for-a-gateway-or-custom-model
-id to set the window.
所在位置 C:\Users\17591\AppData\Roaming\npm\claude.ps1:14 字符: 3
+   & "$basedir/node_modules/@anthropic-ai/claude-code/bin/claude.exe"  ...
+   ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (Claude Code doe...set the window.:String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError
 
[claude-code:unrecognized_model] {"model":"deepseek-flash","query_source":"sdk"}
We're changing auto mode to no longer charge for classifier requests in Claude Code. However, this session isn't eligib
le because your requests go through api.deepseek.com, which isn't compatible with this update. Nothing breaks: auto mod
e keeps working, and its classifier requests are billed as before. To fix it and access the new version of auto mode, a
sk your gateway to implement: https://code.claude.com/docs/en/auto-mode-classifier-billing
> 说明：若本文件顶部出现 14 行 `Claude Code doesn't recognize the model "deepseek-flash"` 告警，那是执行本次审计的 CLI 启动 stderr，不属于审计内容，可直接删除；审计正文从下方标题开始。

# 独立审计报告：核对"功能模块、报警上传、数据处理推送都搞好了，只差真机联调"

- 审计日期：2026-10-28
- 审计对象：`D:\Desktop\防爆机器人`（当前 HEAD `31acee4`）
- 审计方式：以代码为准，逐条 Grep/Read；允许的两条命令已实际执行（结果见文末附录）。
- 审计约束：未修改任何源码、未新增功能；本文件是唯一写入物。

---

## 0. 结论先行

### 0.1 一句话结论

**"只差真机联调"不成立。**

这句话把三类不同性质的事情混成了一件：

1. **已经写好、但只在模拟器上跑过**的（单机巡检、报警规则、传感器接入、报表）；
2. **代码里根本没有**的（多机调度、分区避让、选车、地图切换、导览、MES/SCADA/消防适配器、任务级导出）；
3. **写了但闭环不成立或生产不可用**的（暂停/停止确认、报警升级搁置、MySQL 自动备份、CI、重启恢复）。

即使明天真机到场，第 2 类不会因为"联调"而出现；第 3 类也不是联调能修的，是要改代码和部署的。

### 0.2 统计

对 prompt 要求的 15 个核实项（A1–A5、B6–B9、C10–C13、D14–D15）：

| 判定 | 数量 | 项目 |
|---|---|---|
| 成立 | 1 | C10 遥测入库/聚合/清理已调度 |
| 部分成立 | 11 | A1、A3、A5、B6、B7、B8、B9、C11、C12、C13、D14 |
| 不成立 | 3 | A2、A4、D15 |

A1 整体记为"部分成立"；其"暂停/停止"子项单独判为不成立（见 A1 与 E16）。

### 0.3 五条最硬的反证

1. **项目自己的 README 就写着没开放写操作**：`README.md` 标题为"防爆巡检机器人管理平台"，版本行写"`0.1.0` —— 只读阶段。等真机到场（2026-11-10）联调后开放写操作"；并明确"任务下发/暂停/取消、点位同步到机器人、地图下发、云台控制"处于"明确锁着"状态。
2. **"暂停/停止"没有闭环**：JCROB 暂停直接抛 `NotSupported`；X30 的"暂停"实际是取消，"继续"是空操作；取消任务后平台不回读机器人状态就写 `cancelled`；人工接管只改数据库、不发任何停车命令（证据见 A1）。
3. **多机器人调度不存在**：只有"同一台车同时一个 running 任务"的互斥；没有选车、分配、分区、跨车避让；点位资源锁的返回值被忽略，抢不到锁也照样执行动作（证据见 A2）。
4. **工程基线有确定性故障**：GitHub Actions 后端 job 因 `server/requirements.txt` 根本不存在而在安装依赖步必失败；生产 MySQL 的"每日自动备份"只支持 SQLite，实际不生效；服务重启时把残留 running 任务标 failed 的代码因 `_SL` 未定义抛 `NameError` 被吞掉，从未执行（证据见 D14/C13）。
5. **没有任何真机记录**：兼容性结论表 5 行全空；联调报告明确写"不含真机"；长稳只有 3 分钟；8h、弱网、HIL 全部未做（证据见 D15）。

---

## 1. A. 功能模块

### A1. 任务全生命周期：创建→下发→执行→暂停/终止→复盘→导出

**判定：部分成立。** 创建、下发、执行、详情有实现；但"暂停对 JCROB/X30 都可用""终止确认车真的停""任务级复盘导出"三项不成立。

**已成立的部分**

- 创建：`POST /task-runs` 从模板展开成 planned 任务与步骤，`server/app/api/v1/task_runs.py:149`、`:159-179`。
- 下发：`POST /task-runs/{id}/dispatch`，`server/app/api/v1/task_runs.py:272-292`；服务层 `server/app/services/task_dispatch.py:185-262`。写开关默认关，关闭时 403 `WRITE_LOCKED`：`task_dispatch.py:40-54`。
- 执行：巡航 `POST /task-runs/{id}/cruise`（`task_runs.py:336-381`）→ `CruiseRunner` 逐点 `goto`→轮询→到点动作，`server/app/services/cruise.py:70-169`；单次下发另有 `_poll_until_done`，`task_dispatch.py:255-304`。
- 复盘素材：`GET /task-runs/{id}` 返回步骤、结果、错误，`task_runs.py:139-146`、`:94-104`。

**不成立/残缺的部分**

- **JCROB 没有暂停**：能力声明 `"supports_pause": False`（`server/app/adapters/jcrob/http_adapter.py:57`），调用时直接抛 `NotSupported("JCROB 没有独立的暂停接口（只能取消任务）")`（同文件 `:246-250`）。前端"暂停"按钮不读能力位，照样渲染（`web/src/pages/TaskRuns.vue:265-266`）。
- **X30 的暂停是取消、继续是空操作**：`supports_pause: False`（`server/app/adapters/deeprobotics/adapter.py:38`）；`pause()` 实际调 `client.cancel`（`:157-159`）；`resume()` 只返回一句"X30 无独立继续命令，需重新下发目标点"（`:161-162`），不恢复导航。
- **巡航中暂停不生效**：`CruiseRunner` 循环只检查 `stop.is_set()`（`cruise.py:86-88`），`task_dispatch.pause()` 不会通知巡航线程，暂停后下一个点仍会继续下发。
- **X30 多点多动作只取第一个**：`first = actions[0]`（`deeprobotics/adapter.py:139`），模板里多个动作/点位被静默丢弃。
- **模板下发永远是 501**：`POST /task-templates/{id}/dispatch` 直接 `status_code=501`（`server/app/api/v1/task_templates.py:196-206`）。
- **终止不确认车停**：`task_dispatch.cancel()` 调完 `adapter.cancel` 立刻 `run.status = "cancelled"` 并 commit，之后不读 `get_order`/不校验位置/不校验速度（`task_dispatch.py:327-335`）；巡航取消同样直接写 `cancelled`（`cruise.py:157-168`）。
- **人工接管不会让车停**：`takeover()` 只把 running 任务改成 cancelled（`server/app/services/task_lock.py:51-67`），路由 `POST /robots/{id}/takeover` 只调用它并写审计（`server/app/api/v1/robots.py:179-193`），**完全没有 adapter.cancel 调用**。
- **没有任务级导出/复盘报告**：`server/app/api/v1/reports.py` 不引用 `TaskRun`；`export.xlsx` 只有概览/告警/环境/响应闭环/运行五张表（`reports.py:419-548`）。前端 History 的导出是机器人侧任务浅列表（`web/src/pages/History.vue:94-103`），不含点位结果/照片。
- **任务不记录地图**：`TaskRun` 无 `map_id` 字段（`server/app/models/task_run.py:30-54`），下发订单也不带地图名。

> 交付文档自己承认："停止不是安全急停，只做取消当前任务；失联时平台不具备远程停车能力"——`docs/交付说明-一期范围.md:42-43`。

---

### A2. 多机器人：任务分配 / 冲突避让 / 分区调度

**判定：不成立。** "一车一任务互斥"不等于多机调度。

**证据**

- 只有同车互斥：`active_run()` 按 `status == "running"` + `robot_id` 查（`server/app/services/task_lock.py:23-35`），冲突返回 409 `RUN_BUSY`（`:38-48`）。
- 没有选车/分配器：空 `robot_id` 直接回落到 1 号车，`server/app/api/v1/task_runs.py:266` `rt = robot_registry.get(run.robot_id or 1)`；从模板创建任务时不复制模板的 `robot_id`（`task_runs.py:159-179`），前端也不传（`web/src/pages/TaskRuns.vue:91-95`）。
- **地图/点位接口的 `robot_id` 是形同虚设的**：`get_adapter()` 直接返回全局 `request.app.state.adapter`（`server/app/api/deps.py:82-84`），`/robots/{robot_id}/maps|map/current|map/png|nav-points` 都复用它（`server/app/api/v1/robots.py:216-252`），换 `robot_id` 不会换适配器。
- 资源锁是进程内字典，注释自己写明多实例必须换 DB/Redis：`server/app/services/resource_lock.py:20-21`、`:7-8`。
- **点位锁抢不到也照跑**：`cruise.py:131-140` 的 `got = try_acquire(...)` 返回值只用于 finally 里决定要不要 release，`try:` 内无条件执行 `_do_action`；导航/行驶阶段完全没有锁。
- 没有 zone/区域模型：生产代码里的 `zone` 只有防爆区域字段 `Robot.ex_zone`（`server/app/models/robot.py:41`）；`PlatformMap` 只有 `floor/station`（`server/app/models/map_library.py:23-24`），没有区域表、区域几何、区域占用或分区调度。
- 项目交付范围把多机调度列为二期：`docs/交付说明-一期范围.md:37`。

---

### A3. 多地图/跨区域：点位绑定地图、地图切换

**判定：部分成立。** 点位绑定地图成立；"让机器人切换当前地图"不成立；任务不记录地图。

**证据**

- 点位确实绑定地图：`PointDraft.map_id`（`server/app/models/map_library.py:49`），按 `map_id` 过滤（`server/app/api/v1/map_library.py:185-193`），新增点位做图幅范围校验（`:206-217`），模板校验点位必须属于所选地图（`task_templates.py:85-87`，错误码 `POINT_MISMATCH`）。
- 多地图模型存在：`PlatformMap.floor/station/robot_map_name`（`models/map_library.py:23-32`）。
- **没有切换机器人当前地图的接口**：`robots.py:216-252` 全是 GET；适配器 `PATHS` 里没有厂商的 `switch_map`（`server/app/adapters/jcrob/http_adapter.py:23-47`，厂商文档见 `docs/PDF接口原文索引.md:152`）。前端的"切换"只是换显示数据源（`web/src/pages/MapPage.vue:150-162`）。
- **X30 地图能力为空**：`list_maps()` 直接 `return []`（`deeprobotics/adapter.py:115-117`），且类没有 `get_current_map/get_nav_points/get_map_png`；而 `robots.py:222-252` 无条件调用这些方法，X30 上会 `AttributeError`（500）。
- **点位同步到机器人是 501**：`POST /maps/library/points/{id}/sync` 返回 501（`server/app/api/v1/map_library.py:397-406`）。
- **任务不记录地图**：`TaskRun` 无 `map_id`（`models/task_run.py:30-54`），`_order_payload` 只有坐标/点名（`task_dispatch.py:120-145`）。

---

### A4. 导览能力：语音导览、线路切换、游客交互

**判定：不成立。平台定位是工业巡检，不是导览。**

**证据**

- README 标题与首句："防爆巡检机器人管理平台……单台 JCROB 轮式防爆巡检机器人"（`README.md:1-3`）。
- 服务端没有 tour/guide/narration/greeting/TTS 路由；全仓只命中：
  - 能力标签 `"speaker": ["audio.tts"]`（`server/app/services/capabilities.py:34`），无任何 TTS 实现；
  - 前端面板名"语音喊话"（`web/src/components/panels/registry.ts:23`），是面板占位；
  - `MapPage.vue` 的 `.map-guide` 是页面操作指引的 CSS 类名，不是业务导览（`web/src/pages/MapPage.vue:288`）。
- "导览"字样只出现在参考素材路径（`HANDOFF.md:62`）和 UI 参考文档（`docs/UI设计基线-实拍参考.md:3`），且明确写"是别人家产品的 UI 参考，不是本项目机器人"。
- 厂商文档有 `PUT /system/greeting`（`docs/PDF接口原文索引.md:51`），适配器未实现（`http_adapter.py:23-47`）。

---

### A5. 第三方对接：MES/SCADA/消防/工单系统

**判定：部分成立。** 有通用入站 API Key 和通用出站 webhook；没有 MES/SCADA/消防标准接口或适配器。

**证据**

- 通用入站：`VALID_SCOPES = ("task:ingest", "ai:write", "sensor:write", "read:alarms")`（`server/app/api/v1/api_clients.py:23`），鉴权在 `server/app/services/api_auth.py:50-83`。
- 通用出站：通知类型 `wecom/dingtalk/generic/email/sms`（`server/app/services/notify.py:32-38`），generic 载荷 `:74-92`。
- **没有 MES/SCADA/消防适配器或路由**：服务端 Grep `\bMES\b|SCADA|消防|firefight|SAP|ERP` 只命中一处无关的测温提示（`server/app/services/cruise.py:236`）。
- 外部接口只是占位规范：`docs/外部接口占位规范.md:219-230` 明确"先只定路径和最小字段，不实现"，包括消防 `GET /api/v1/fire/status`、工单 `POST /api/v1/workorders`；实际工单是内部 `/work-orders`（`server/app/api/v1/inspection.py:455-625`）。
- `contracts/openapi.json` 只覆盖早期 17 条只读接口，缺 `/task-runs`、`/maps/library`、`/ai`、`/work-orders`（`contracts/openapi.json:7` 起）。

---

## 2. B. 报警上传

### B6. 机器人/设备能否主动上报报警？是否有"设备报警接入"接口？

**判定：部分成立。** 设备可以上报"读数/AI 结果"，由平台规则生成报警；但没有"设备直接提交一条报警"的接口。

**证据**

- 报警路由只有查询与工作流（列表、搁置、取消搁置、KPI、最新、处置、关闭、统计、确认），**没有 POST 创建报警**：`server/app/api/v1/alarms.py:17,64,94,111,177,198,221,248,291`。
- 设备可走的间接路径：
  - 传感器读数 `POST /sensors/{id}/readings/ingest`（API Key、`sensor:write`），`server/app/api/v1/sensors.py:184-193`；阈值判断后由平台触发报警。
  - AI 结果 `POST /ai/results`（`ai:write`），`server/app/api/v1/ai.py:102`，置信度达阈值后调 `raise_external`（`ai.py:147`）。
  - 外部报警入口 `raise_external()`（`server/app/services/alarms.py:357-361`）只被平台内部调用，不是公开的设备报警接入路由。
- 机器人任务状态回传 `POST /task-runs/ingest`（`task_runs.py:193-260`）是任务状态，不是报警。

**结论**：设备能"上报数据"，不能"上报报警"；报警始终由平台规则/平台内部调用生成。

---

### B7. 传感器读数接入路径（HTTP ingest / WS / Modbus 网关），分别是否验过？

**判定：部分成立。** 四条路径代码都在；只有 Modbus TCP 有端到端假从站测试；HTTP ingest、WS、MQTT 未做端到端；Modbus RTU-over-SSH 从 API 层根本建不出来。

| 路径 | 实现 | 验证情况 |
|---|---|---|
| HTTP ingest | `sensors.py:184-193`（API Key）、`:196-204`（会话+CSRF） | **无端点级测试**（`grep -rn "readings/ingest" server/tests` 无结果） |
| 机器人 WS 推送 | `server/app/services/env_ws.py:134-174`，1s ping、指数退避重连 | 仅解析函数单测 `server/tests/test_env_ws.py:7`（`parse_payload`），不测连接/入库 |
| Modbus TCP | 手写 MBAP + 功能码 03/04，`server/app/services/sensor_gateway.py:33-59` | **有端到端假从站测试**：`server/tests/test_api.py:775-835` |
| Modbus RTU over SSH | `sensor_gateway.py:115`、`:239-265` | **API 层不可达**：`GatewayIn.protocol` 正则只允许 `^(modbus\|mqtt)$`（`server/app/api/v1/sensor_gateways.py:24`）；模型注释也只写 `modbus/mqtt`（`server/app/models/sensor_gateway.py:22`） |
| MQTT | `sensor_gateway.py:268-306`（paho 客户端） | 无测试 |

补充：传感器"N 分钟聚合"是查询时降采样，不落聚合表（`sensors.py:300-311`），与遥测的分钟桶是两套。

---

### B8. 报警外发：企微/钉钉/webhook/邮件/短信，各自是否真的能发？端到端验过吗？

**判定：部分成立。** 发送代码是真实网络调用，不是空壳；但只有短信有本地假网关端到端测试，企微/钉钉/邮件/通用 webhook 都没有端到端证据；"语音"只是标签。

**证据**

- 真实发送实现：
  - HTTP 类（企微/钉钉/generic/sms）：`_send_http()` 用 `httpx.Client().post`，8s 超时，检查 HTTP 状态与 `errcode`（`server/app/services/notify.py:80-120`）。
  - 邮件：`smtplib.SMTP/SMTP_SSL`，支持 STARTTLS、登录（`notify.py:123-150`）。
  - 载荷：企微 markdown（`:54-55`）、钉钉 markdown（`:58-60`）、短信 `{to,text,alarm}`（`:63-71`）、generic `{event,alarm,text}`（`:74-75`）。
- 端到端：
  - 短信：`server/tests/test_notify_sms.py:13-42` 起本地假 HTTP 服务收包，验 payload 与 HMAC 头。**通过。**
  - 通用 webhook：`server/tests/test_api.py:458-555` 验 HMAC 与失败重试。**通过。**
  - 企微/钉钉/邮件：测试只创建通道/空配置（`test_api.py:112,123`），**没有一次真实发送的端到端测试**。
- **"语音"没有实现**：`TYPE_LABELS["sms"] = "短信/语音网关（HTTP）"`（`notify.py:37`），实际载荷只有 `to/text/alarm`（`:63-71`），没有 TTS、语音文件、voice call 字段或厂商语音 API 适配。
- **钉钉签名风险**：代码发的是自定义 `X-Jcrob-Timestamp/X-Jcrob-Signature` 头（`notify.py:97-103`）；钉钉自定义机器人开启"加签"时要求 URL 上的 `timestamp` + `sign` 查询参数，不认这个头。若客户机器人开了加签，会直接失败。
- 配置侧：创建 sms 类型不强制 URL（`server/app/api/v1/notify.py:84-86` 只校验 wecom/dingtalk/generic 的 url 和 email 的 host/to），可以建出一条永远发不出去的短信通道。

---

### B9. 报警升级（SLA/超时升级）是否真的会触发？搁置期间是否暂停？

**判定：部分成立。** 定时器确实每 60 秒跑；但报警升级**不排除搁置告警**，且没有 tier=2 通道时也会把 `escalated_at` 标记掉；UI 无法创建 tier=2 通道；无测试。

**证据**

- 升级循环：`NotifyDispatcher._loop()` 每 60 秒调用 `escalate_once()` 与 `retry_once()`（`server/app/services/notify.py:204-216`）。
- 升级条件：critical、未确认、未关闭、未升级、`started_at <= now - escalate_after_min`（默认 5 分钟），`notify.py:267-284`。
- **不排除搁置**：查询条件里没有 `shelved_until` 过滤（`notify.py:274-284`）；对比工单升级明确跳过搁置来源告警（`server/app/services/work_orders.py:61-83`），说明"搁置应暂停 SLA"的产品意图只在工单侧实现，报警外发侧没实现。
- **无通道也标记已升级**：先 `alarm.escalated_at = datetime.now()`，再 `if not chiefs: continue`（`notify.py:294-297`）。结果是升级事实被吞掉，之后即使补建 tier=2 通道也不会再升级。
- **UI 无法建 tier=2**：`web/src` 全目录 Grep `tier` 无结果；API 虽接受 body 的 tier，但前端没有入口。
- **SLA 矩阵只用于工单 due_at**：`DEFAULT_MINUTES = {"P1": 30, "P2": 120, "P3": 480, "P4": 1440}`（`server/app/services/sla.py:13`），只落到工单 `due_at`（`:45`）；报警升级用的是 `notify.escalate_after_min`，不是这张 SLA 矩阵。
- 测试：`grep -rn "escalate\|shelve" server/tests` 只命中通道创建，无升级/搁置行为测试。

---

## 3. C. 数据处理与推送

### C10. 遥测/环境数据：入库、聚合、保留期清理，是否都在跑？

**判定：成立。** 三条链路都已接入 lifespan 并定时执行；但没有任何测试，也没有健康检查项。

**证据**

- 采集：`TelemetryCollector`，`SAMPLE_INTERVAL_S = 10`（`server/app/api/v1/telemetry.py:30`），循环 `:54`，读取 `snap.info/pose/status/galileo` 后入库 `:70-90`；在 `server/app/main.py:145-149` 启动。
- 聚合：`rollup()` 按分钟桶幂等写入（`telemetry.py:101-139`），由 `_telemetry_janitor` 每 6 小时对最近 26 小时执行一次（`main.py:159-192`，调用点 `:167`）。
- 保留期：遥测 `purge(keep_days=7)`（`telemetry.py:142-147`，`main.py:172`）；环境读数单独 90 天（`main.py:174-185`）。
- 表与迁移：`telemetry_sample` / `telemetry_rollup`（`server/app/models/telemetry.py:20-55`），迁移 `server/alembic/versions/0023_telemetry_rollup.py`。
- 注意点：
  - janitor 是裸 daemon 线程，所有异常被 `except Exception: pass` 吞掉（`main.py:170-171,184-187`），没有 health 条目；
  - 聚合结果只有 `GET /telemetry/rollup`（`telemetry.py:150-170`），**前端没有任何地方调用**，等于"算了但没展示"；
  - 无测试：`grep -rn "telemetry\|rollup\|purge" server/tests` 无结果。

---

### C11. 前端实时性：WebSocket 推送还是轮询？"数据刷新 1s"是推送还是轮询？

**判定：部分成立。是轮询，不是推送。** 状态 1 秒轮询，环境数据 15 秒轮询；"数据刷新 1s"只是写死的页脚文案。

**证据**

- 后端没有任何浏览器 WebSocket/SSE 路由：`grep -rn "websocket" server/app` 只命中 `env_ws.py:134,144`，那是服务端**主动连机器人**的客户端，不是给浏览器的推送。
- nginx 配了 `/ws/` 代理块（`deploy/nginx/default.conf:91-97`），但后端没有对应端点，是死配置。
- 前端全部 `setInterval` + `fetch`：
  - 机器人状态 1s：`web/src/stores/robot.ts:4` `POLL_MS = 1000`，`:63` `window.setInterval(...)`；告警每 5 拍拉一次（`:5,35`）。
  - 环境 15s、视频健康 10s、趋势 60s、任务 10s、feed 15s、未读 30s：`web/src/pages/Dashboard.vue:137-147`、`:645-655`（重复定义）。
  - 环境页 15s：`web/src/pages/EnvMonitor.vue:70-71`。
- "数据刷新 1s"是写死文本 `Dashboard.vue:1036`，只对应状态轮询；环境数据并不是 1 秒。
- 无前端实时性测试。

---

### C12. 视频：go2rtc 拉流、转码、MJPEG 推送；无人观看是否自动停？

**判定：部分成立。** ffmpeg 转 MJPEG + 无人观看自动停是真的；go2rtc 在仓库里没有被部署，默认配置也没连上；无测试。

**证据**

- 转码 + MJPEG：`video_stream.py:71-90` 每个摄像头起一个 ffmpeg（`-rtsp_transport tcp ... -f image2pipe -vcodec mjpeg`），`videos.py:408-464` 输出 `multipart/x-mixed-replace`。
- 共享与计数：`acquire()/release()` 复用同一 ffmpeg，`viewers` 计数（`video_stream.py:139-161`）。
- **无人观看自动停**：`IDLE_SECONDS = 20`（`video_stream.py:52`），janitor 每 5 秒扫描，超过 20 秒没有"实际取帧"就 `stop()`（`:176-189`）。注意它按 `last_used`（每帧更新，`videos.py:456`）回收，不是按 `viewers`，效果等价。
- **go2rtc 不在 compose 里**：`deploy/docker-compose.yml` 只有 `jc-server`、`jc-mysql`、`jc-nginx` 三个服务（`:7,44,75`），无 go2rtc。
- **默认部署连不上 go2rtc**：`deploy/README.md:46` 假设宿主机已有 go2rtc（192.168.8.40:1984）；但 `deploy/env` 没有 `JC_GO2RTC_BASE`，只有 `JC_GO2RTC_PUBLIC_BASE: /go2rtc`（`deploy/docker-compose.yml:20`），而 `config.py:63` 默认空字符串。结果后端调 go2rtc API（取 RTSP、注册流、快照）会失败/返回空；浏览器 iframe 仍可用 public base。
- 另外，MJPEG 的 ffmpeg 直接拉 RTSP（`videos.py:52-59,122-145`），go2rtc 只用于查流地址，不是"go2rtc 拉流转码"。
- 无测试：`grep -rn "video_stream\|mjpeg\|IDLE_SECONDS" server/tests` 无结果。
- 死代码：`web/src/components/VideoBox.vue` 是"视频未接入"占位，被 import 但模板从未使用（`Dashboard.vue:6`）；`openVideo()` 只弹 toast（`Dashboard.vue:166-168`）。

---

### C13. 平台→设备指令通道：是否只有 HTTP/TCP 请求-响应？断线重连、失败重试、离线缓存？

**判定：部分成立。** 只有请求-响应；JCROB 写操作明确不自动重试、无离线队列；X30 TCP 有一次重连；有下单幂等/租约对账；但"重启恢复"代码实际从未执行。

**证据**

- `command_gateway.py` 不是网关，只是纯函数 `precheck()`（`server/app/services/command_gateway.py:13-27`），只被只读预检接口调用（`robots.py:307-313`），真实下发不走它。
- JCROB 下发是单次 POST：`http_adapter.py:224`；`task_dispatch.py:228-242` 捕获异常后保持 `sending`，明确写"已进入对账，不会自动重发"。`adapters/jcrob/client.py` 也不做重试。
- **无离线缓存/发件箱**：`grep queue|outbox` 只命中通知队列（`notify.py`），指令侧没有。
- 已有的可靠性机制（这部分是加分项）：
  - 下单幂等 + 租约：迁移 `0024_dispatch_idempotency.py`，`_claim_dispatch()` 条件 UPDATE，重复下单 409 `ORDER_IN_FLIGHT`（`task_dispatch.py:151-182`）。
  - 对账：`reconcile_dispatches()` 每 60 秒跑（`main.py:229-243`），租约过期无回执标 failed，有 external_id 标 sent，不盲重发（`task_dispatch.py:410-438`）。
  - X30 TCP：`for attempt in (0, 1)`，失败 close 后重连一次（`server/app/adapters/deeprobotics/protocol.py:147-159`）。
- **重启恢复是死代码（确定性 bug）**：`main.py:79-81` 用 `_SL()` 把残留 `running/dispatched` 标 failed，但 `_SL` 直到 `main.py:142` 才 import；运行时抛 `NameError`，被 `main.py:89-90` 的 `except Exception: pass` 吞掉。**这段恢复从未执行。** 崩溃后任务会一直显示"执行中"。
- 每次 dispatch 另起一个未跟踪的 daemon 线程做 `_poll_until_done`（`task_dispatch.py:257-261`），停机时不 join/不取消。
- 测试：幂等/对账有测试 `server/tests/test_dispatch_idempotency.py:27-77`；重试/离线/重启恢复无测试（因为没有实现）。

---

## 4. D. 工程与运维

### D14. 单 worker？MQ/Redis/时序库/对象存储？备份自动化？CI 真能跑？

**判定：部分成立。**

| 子项 | 判定 | 证据 |
|---|---|---|
| 单 worker | 成立 | `deploy/entrypoint.sh:12-18` 明确 `--workers 1`；`server/app/main.py:3-5` 自述"只能 --workers 1"；compose 只有 1 个 `jc-server` |
| 无 Redis/MQ/时序库/对象存储 | 成立 | compose 仅 `jc-server/jc-mysql/jc-nginx`；`server/pyproject.toml:6-22` 无 redis/kafka/influx/boto3/minio；`paho-mqtt` 只作现场传感器客户端 |
| 自动备份 | **部分成立/生产不生效** | 进程内 `_backup_janitor` 每天 02:00 用 `sqlite3` 备份（`main.py:195-227`），但 `sqlite3.connect(src)` 只认 SQLite；生产 compose 是 `mysql+pymysql://...`（`deploy/docker-compose.yml:18`），路径解析失败后异常被吞（`main.py:223-224`）。`deploy/backup.sh:7-8` 自己写"建议加进 crontab"，`install.sh/entrypoint.sh/scripts/deploy.sh` 都不装 cron/systemd timer；`self_check.py` 也不检查备份是否成功 |
| CI 真能跑 | **不成立（后端 job 必失败）** | `.github/workflows/ci.yml:21` 缓存路径与 `:22-23` 安装命令都指向 `server/requirements.txt`；该文件**不存在且从未进入 git**（`ls server/requirements.txt` → No such file；`git ls-files \| grep -i requirements` → 空）。后端 job 在安装依赖步即退出，pytest/alembic 不会执行。前端 job 可过。`scripts/deploy.sh:26` 同样引用该文件，裸机部署也会失败 |
| 默认数据库 | 成立 | `config.py:35` 默认 SQLite；生产 compose 覆盖 MySQL；无 PostgreSQL |

补充：本地实际执行（详见附录）后端 `120 passed`、前端 `npm run build` 通过——**本地绿不等于 CI 绿**，CI 根本到不了测试步。

---

### D15. 真机联调记录、HIL、长稳（≥8h）、弱网测试？

**判定：不成立。**

**证据**

- 联调报告明确写"环境：本机 dev……**不含真机**"，24/24 是模拟器成绩：`docs/reviews/integration-test-report-20261028.md:3-7`；§4.1 写"需要真机/HIL，当前无条件"，真机 X30/JCROB 均不可达，HIL/netem 未做（`:86-94,113-115`）。
- 兼容性结论表 5 行（日期/固件/HTTP/响应/结论）全空：`docs/JCROB实机兼容性.md:70-78`；角度单位"待实测"（`:42-49`）。这是模板，不是记录。
- 长稳只有 3 分钟：3144 请求、0 错误、p50=6ms、p95=13ms、内存 220.8→208.5MB（`docs/reviews/soak-and-ops-20261028.md:3-13`）；同文档 `:12-13` 自认"不等于 7×24"，`:35-38` 列明 8h、弱网、真机断网续跑未做。
- 验收清单自认："真机项只能讲、不能演"（`docs/验收前必测清单.md:40-49`），"7×24 长稳时间不够"（`:47`）。
- 时间上也还不可能：真机 2026-11-10 才到场（`docs/真机联调预案-20261022.md:3`、`README.md:148`），今天是 2026-10-28。

---

## 5. E. 结论

### E16. 已完成 / 部分完成 / 未做 总表

| # | 能力 | 状态 | 关键证据 |
|---|---|---|---|
| A1 | 任务创建/下发/执行/详情 | **部分完成** | 有 `POST /task-runs`、dispatch、cruise、detail；但模板下发 501、X30 只取首动作、任务级导出缺失 |
| A1a | 暂停/继续 | **未做（真机可用）** | JCROB `NotSupported`（`http_adapter.py:246-250`）；X30 pause=cancel、resume=空操作（`adapter.py:157-162`）；巡航不检查 `paused_at` |
| A1b | 终止并确认车停 | **未做** | cancel 后直接写 `cancelled`（`task_dispatch.py:327-335`）；接管只改 DB（`task_lock.py:51-67`） |
| A2 | 多机分配/避让/分区 | **未做** | 只有同车互斥（`task_lock.py:23-48`）；无选车/区域/交通模型；点位锁抢不到也执行（`cruise.py:131-140`）；地图接口不按 robot_id 路由（`deps.py:82-84`） |
| A3 | 点位绑定地图 | **已完成** | `PointDraft.map_id`、范围校验、模板 `POINT_MISMATCH` |
| A3a | 地图切换/任务记录地图 | **未做** | 只有 GET 地图接口；无 switch_map 适配器；`TaskRun` 无 `map_id`；点位同步 501 |
| A4 | 导览/讲解/游客交互 | **未做** | 无路由/无 TTS；只有 `audio.tts` 能力标签和"语音喊话"面板名 |
| A5 | 通用 API Key / webhook | **已完成** | `api_clients.py:23`、`notify.py:32-38,74-92` |
| A5a | MES/SCADA/消防/工单适配器 | **未做** | Grep 无实现；`docs/外部接口占位规范.md:219-230` 明确只占位 |
| B6 | 设备上报数据→平台生成报警 | **部分完成** | 传感器 ingest、AI results、`raise_external`；无设备直接报警接口（`alarms.py` 无 POST 创建） |
| B6a | 设备直接报警接入 | **未做** | 同上 |
| B7 | HTTP / WS / Modbus / MQTT 接入 | **部分完成** | 四路径有代码；仅 Modbus TCP 有假从站 E2E；HTTP ingest/WS/MQTT 未验；RTU-over-SSH API 不可达 |
| B8 | 企微/钉钉/webhook/邮件/短信 | **部分完成** | 发送实现真实；仅短信、generic webhook 有 E2E；企微/钉钉/邮件未验；语音仅有标签 |
| B9 | 报警升级 | **部分完成** | 每 60s 触发；但搁置不暂停、无 tier=2 时也标记已升级、UI 无 tier=2 入口、无测试 |
| C10 | 遥测入库/聚合/清理 | **已完成（未测试）** | `main.py:145-149,159-192`；`telemetry.py:30,101-147` |
| C11 | 前端实时推送 | **部分完成** | 无 WS/SSE；状态 1s 轮询、环境 15s；`/ws/` 是死配置；"1s"是写死文案 |
| C12 | 视频转码/MJPEG/自动停 | **部分完成** | ffmpeg + MJPEG + 20s idle 停真实；go2rtc 不在 compose、默认 env 未配置；无测试 |
| C13 | 指令通道重试/重连/离线缓存 | **部分完成** | 仅请求-响应；JCROB 不重试、无离线队列；X30 一次重连；有幂等/对账；重启恢复因 NameError 从未执行 |
| D14 | 单 worker/无中间件 | **已完成** | `entrypoint.sh:12-18`、compose 3 服务 |
| D14a | 自动备份 | **部分完成/生产不生效** | 仅 SQLite；MySQL 下异常被吞；无 cron |
| D14b | CI | **未做（后端必失败）** | `ci.yml:21-23` 引用不存在的 `server/requirements.txt` |
| D15 | 真机/HIL/≥8h/弱网 | **未做** | 报告明确不含真机；仅 3 分钟浸泡；兼容性表全空 |

### E17. "只差真机联调"是否成立？还差哪几件？

**不成立。**

真机联调只能验证"协议能不能通、坐标对不对、到点准不准"。以下 8 件是**代码/部署层**的缺口，真机到场也不会自动消失，按对验收/交付的影响排序：

1. **任务控制闭环（安全相关）**：JCROB 无暂停、X30 暂停=取消、巡航暂停不生效、取消/接管不回读确认。客户现场一定会按"暂停—继续—停车"验收，这是最容易当场翻车的项。
2. **多机调度与地图路由**：无选车/分配/避让/分区；点位锁抢不到仍执行；地图/点位接口不按 `robot_id` 路由；X30 地图接口会 500。只要现场超过 1 台车或 1 张图，就会被问倒。
3. **工程基线**：CI 后端必失败（缺 requirements.txt）、生产 MySQL 自动备份不生效、重启恢复代码从未执行。这三件直接影响"能不能交付、出了事能不能恢复"。
4. **报警外发与升级的真实端到端**：企微/钉钉/邮件未实测、钉钉加签不兼容、语音未实现、搁置告警仍升级、无 tier=2 配置入口。客户说"现在就发一条到我手机"时无法保证。
5. **实时推送缺失**：全前端轮询，状态 1s、环境 15s；nginx `/ws/` 是死配置。若标书/口头承诺过"实时推送"，这是硬伤。
6. **视频链路可部署性**：go2rtc 不在 compose、默认 env 未配置、无任何视频测试；现场黑屏时没有可复现的部署路径。
7. **任务复盘/导出/地图溯源**：没有任务级导出，`TaskRun` 不记录 `map_id`，模板下发 501、点位同步 501。验收要"跑完给我一份报告"时只能手工拼。
8. **数据接入路径的测试覆盖**：HTTP ingest、机器人 WS、MQTT、Modbus RTU 都没有端到端测试；遥测采集/聚合/清理零测试。现在只有"代码看起来对"，没有回归保护。

> 第 9 件（不计入 8 条）是 D15 本身：真机/HIL/8h/弱网。它不是"只差"的那一件，而是**在以上 8 件之后**还要做的一整轮验证。

### E18. 明天客户验收，最可能被当场问倒的 5 个问题与真实答案

**Q1：现场演示一下"暂停"，车停住，再"继续"。**
真实答案：演示不了。JCROB 没有暂停接口，点了会报"不支持"；X30 的暂停实际是取消任务，"继续"不会恢复导航，只能重新下发目标点；巡航任务点暂停后，平台仍会继续下发下一个点。我们只能演示"取消任务"，且取消后平台不回读机器人状态确认已停。

**Q2：两台车同时跑，怎么派单、怎么避免抢同一个点位/窄道？**
真实答案：没有派单。现在只有"同一台车同时只能有一个 running 任务"的数据库互斥；没有按电量/距离/负载选车，没有分区，没有跨车避让。点位锁虽然有表，但抢不到锁动作照样执行；而且地图/点位接口的 `robot_id` 没有真正路由到对应机器人。多机调度在交付范围里被列为二期。

**Q3：断网/平台重启后，任务会不会重复下发？会不会一直显示"执行中"？**
真实答案：不会重复下发——我们有下单幂等、租约和对账，明确不盲重试，这是设计正确的部分。但平台重启时"把残留 running 任务标 failed"的代码因为变量 `_SL` 在使用后才 import，实际抛 `NameError` 被吞掉，**从未执行**；所以重启后任务可能一直显示执行中，需要人工处理。也没有离线缓存/发件箱。

**Q4：现在发一条报警到我企业微信/钉钉/手机短信，搁置后还会升级吗？**
真实答案：发送代码是真实 HTTP/SMTP 调用，不是假的。但只有短信和通用 webhook 在本地假网关上做过端到端；企微、钉钉、邮件没有实测记录。钉钉如果开了"加签"，我们发的是自定义 HMAC 头，不是钉钉要求的 URL 参数，可能被拒。语音只是通道标签，没有 TTS/语音外呼实现。另外，搁置中的 critical 告警仍会被升级外发（工单升级会跳过搁置，报警升级不会），而且前端没有创建 tier=2 升级通道的入口。

**Q5：CI 是绿的吗？数据库每天自动备份吗？跑过 8 小时和弱网吗？**
真实答案：本地 `pytest` 是 120 passed，前端 `npm run build` 通过；但 GitHub Actions 的后端 job 会失败——CI 配置引用 `server/requirements.txt`，这个文件不存在、也从未进过 git，安装在第一步就退出。自动备份只在 SQLite 下生效，生产 compose 用的是 MySQL，每日 02:00 的备份线程会异常并被吞掉；`backup.sh` 需要手工加 crontab，部署脚本不装。长稳只做过 3 分钟（3144 请求、0 错误），8 小时、弱网、HIL、真机全部没做；兼容性结论表现在还是空的。

---

## 附录：本次实际执行的命令与结果

### A. 后端测试

```text
$ cd server && python -m pytest -q
120 passed, 2 warnings in 28.27s
```

两条 warning：

1. `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated`；
2. `PytestUnhandledThreadExceptionWarning`：`test_migrations.py` 的 subprocess 读取线程在中文 Windows 上 `UnicodeDecodeError: 'gbk' codec can't decode byte 0xae`（测试本身仍 passed）。

### B. 前端构建

```text
$ cd web && npm run build
（build = vue-tsc --noEmit && vite build）
✓ built in 2.48s
```

### C. CI 关键文件核查

```text
$ ls server/requirements.txt
ls: cannot access 'server/requirements.txt': No such file or directory
$ git ls-files | grep -i requirements
（无输出）
```

`.github/workflows/ci.yml:21-23` 仍引用 `server/requirements.txt` → 后端 job 必失败。

### D. 真机连接性

本次未尝试连接真机（审计环境不在现场网络；项目文档也记录 192.168.1.106 / 192.168.1.100 不可达：`docs/reviews/integration-test-report-20261028.md:113-115`）。因此本报告不对"真机协议是否通"下结论，只对"代码是否具备该能力、是否验证过"下结论。

---

## 审计边界声明

- 本报告只核实代码与仓库内证据；未修改任何源码、配置、迁移或测试。
- "成立"指代码路径完整且调度/入口存在；"部分成立"指主路径存在但关键子项缺失、未验证或生产不可用；"不成立"指该能力在代码中不存在，或声称的闭环不成立。
- 未把"文档里写了"当作实现证据；文档只用于对照宣称与自认缺口。
