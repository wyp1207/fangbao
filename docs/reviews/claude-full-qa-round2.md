Claude Code doesn't recognize the model "deepseek-flash", so it assumes a context window of 200k tokens. Update Claude Code, or see https://code.claude.com/docs/en/model-config#correct-the-window-for-a-gateway-or-custom-model-id to set the window.
[claude-code:unrecognized_model] {"model":"deepseek-flash","query_source":"sdk"}
We're changing auto mode to no longer charge for classifier requests in Claude Code. However, this session isn't eligible because your requests go through api.deepseek.com, which isn't compatible with this update. Nothing breaks: auto mode keeps working, and its classifier requests are billed as before. To fix it and access the new version of auto mode, ask your gateway to implement: https://code.claude.com/docs/en/auto-mode-classifier-billing
<!-- 说明：本文件开头 3 行是 Claude Code 运行环境诊断输出（模型名/计费提示），不是验收报告内容。 -->

# 第二轮端到端验收报告（浏览器 + 接口 + 数据库交叉验证）

- 验收时间：2026-10-27 14:14–14:35（UTC+8）
- 前端：`http://127.0.0.1:5173`；后端：`http://127.0.0.1:8000/api/v1`；账号：`admin`
- 数据库：`server/data/app.db`（SQLite，WAL）
- 方法：Playwright 真实点击；同时抓取请求 URL/状态码；每一步回查 SQLite；报表用真实下载的 xlsx 再用 openpyxl 读取
- 证据目录：`C:\Users\17591\AppData\Local\Temp\qa_r2\`（截图、JSON、`report.xlsx`）
- 说明：本轮没有重启服务。测试期间检测到另一个进程在 14:03–14:15 修改代码/生成告警，后端进程启动于 14:13:39；本报告基于该运行实例，并对当前代码做了运行时验证。

---

## 修复验证（逐条 ✅/❌ + 证据）

### 1. 登录与会话

| 检查项 | 结论 | 证据 |
|---|---|---|
| 清 cookie + 刷新后账号密码清空 | ✅ | 删除 cookie 后刷新落到 `http://127.0.0.1:5173/login?redirect=/dashboard`；账号、密码输入框值均为 `""`（`session.json.A1_cookie_cleared`，截图 `A1_expired_login.png`）。未显示“会话已过期”提示（路由守卫未带 `expired=1`，不影响清空要求） |
| 全局 401 跳登录 | ✅ | 登录态页面触发 401 后 **0.1s** 跳到 `/login?redirect=/dashboard&expired=1`，页面显示“会话已过期，请重新登录（账号密码已清空）”（`session.json.A2_global_401`，`A2_global_401.png`） |
| 空闲 N 分钟自动退出设置生效 | ❌ | 设置页把 `security.idle_minutes` 从 5 改为 1 并保存成功；75s 后仍停留在 `/dashboard`，58.0s 时 `GET /api/v1/auth/me` 返回 **200**，没有退出（`session.json.A3_idle_75s`）。根因见 P1-1 |

### 2. 告警

| 检查项 | 结论 | 证据 |
|---|---|---|
| 搁置必须填原因 | ✅ | 原因为空点“确认搁置”：只弹提示，未发出请求（`requests: []`），库中 `shelved_until/shelve_reason` 仍为 `NULL`（`alarm_chain.json.empty_reason`，`B1_shelve_empty_reason.png`） |
| 到期自动解除 | ✅（有延迟、无审计） | 对告警 194 搁置 1 分钟：`POST /api/v1/alarms/194/shelve` **200**，库中 `shelved_until=2026-10-27 14:16:49.344852`，原因已写，审计 847。到期后第 120s 采样时两个字段被清空，刷新页面“搁置”徽标消失（`alarm_chain.json.auto_restore`，`B2_shelved.png`/`B3_after_expiry.png`）。清理线程 60s 一次，最长延迟约 60s；清理本身没有审计 |
| 关闭告警联动工单 | ✅（单工单）/ ⚠️（多工单代码缺陷） | 194 关联工单 163 关闭前 `open`，`POST /alarms/194/close` **200** 后 0.5s 内变为 `closed`，`resolution="来源告警已关闭（联动）"`（`alarm_chain.json.close`，`B4_alarm_closed.png`）。审计 849 为 `alarm.close`；**没有**工单联动关闭的审计。代码只处理第一张未关闭工单，见 P2-0；本轮没有制造“两张工单+关单”的生产场景，未做破坏性复现 |
| P1–P4 显示 | ⚠️ 部分 | 列表页前 10 条徽标为 `P1,P1,P3,P2,P2...`，P1/P2/P3 均能渲染（`B5_alarm_list_pbadges.png`）。但全库 P4 为 **0** 条；`priority_for()` 只在“既非 critical 也非 warn”时返回 P4，而系统只产生 warn/critical，P4 结构性不可达，见 P2-4 |
| KPI 数字自洽 | ❌ | 数据库/接口/面板标题均为 **206**，环形图总数却是 **200**；未确认库/接口 **198**，环形图/铃铛 **195**；进入首页 2s 时环形图为 **0/0**（`dashboard_video.json.kpi_at_2s/kpi_at_9s`）。原因见 P2-1 |
| 严重告警自动建工单 | ❌ P0 | 当前代码直接调用 `ensure_from_alarm` 抛 `NameError: name 'sla' is not defined`；P1 告警 206/207 在库中均为 `wo=0`。历史 158 条 critical 告警有关联工单，说明该路径曾经可用或历史数据由其他路径生成；当前代码确定失效，且调用点 `except Exception: pass` 把错误吞掉。见 P0-1 |

### 3. 巡检计划

| 检查项 | 结论 | 证据 |
|---|---|---|
| 创建 → 编辑 → 删除 | ⚠️ 后端全通；前端不能新建 | `POST /api/v1/inspection/plans` **200** 创建 id=2；`PATCH /inspection/plans/2` **200**；`DELETE /inspection/plans/2` **200**；删除后 UI 行消失、库中计划数 0（`inspection_chain.json`，`C1/C2/C3`）。但页面只有“编辑/删除”，**没有新建入口**，见 P2-7 |
| 点位行编辑生效 | ✅ | UI 编辑把点位从 2 条改为 3 条：PATCH **200**，返回 `point_count=3`，行文本变为“QA点位1、QA点位2、QA点位3-新增”，库中 `items_json` 同步为 3 个对象（`inspection_chain.json.db_after_edit`，`C2_plan_edited.png`） |
| 审计 | ⚠️ | 创建 843、更新 844、删除 845 均有记录；创建参数只有 `{"points":2}`，更新/删除的 `params_json` 为 `NULL`，无法从审计还原改了什么 |

### 4. 设备

| 检查项 | 结论 | 证据 |
|---|---|---|
| 在线设备“读一次状态”2s 内、结果正确 | ❌ 快但结果错 | 设备 1 `POST /devices/1/status-probe` **200 / 0.08s**，返回 `source="cache"`，`data.status/info/pose` 全空、`age_s=-1.0`、`online=false`，页面提示“JCROB-01：-1 秒前 · 离线”；同一时刻 `/robots/runtime` 显示设备 1 **在线、数据年龄 0.369s**（`settings_devices.json.devices`，`D1_probe_result.png`）。见 P1-3 |
| 离线设备 6s 内返回、不挂死 | ✅ | 设备 2 **6.05s** 返回“探测超时（6 秒内没响应）”；设备 3 **2.3s** 返回 `get_status/get_info: Unreachable`；均未挂死（`settings_devices.json.devices`） |
| 测试连接 | ✅ | 设备 1 点击后 **3.29s** 返回 `{"tcp":false,"http":false,"detail":"TCP 连不上：TimeoutError"}`，页面如实提示（`settings_devices.json.test_connection`，`D2_test_connection.png`）。当前设备为 mock/不可达，这是环境事实，不是假成功 |

### 5. 视频

| 检查项 | 结论 | 证据 |
|---|---|---|
| 首页两路视频、连续帧时间前进 | ⚠️ 只能验证一路 | 可见光连续三帧 md5 均不同（`2c06a9…`/`a82c97…`/`24d93a…`），画面叠加时间从 `14:22:48` 前进到 `14:22:51`，是真实连续流（`dashboard_video.json.frames`，`F1/F2/F3`）。但设备 1 名下只有 1 台可见光相机，热红外相机 4 属于设备 2；首页“热红外视频”显示“视频流未接入 / 热像仪接上后…”，两路同时实时在本环境无法完整验证（`url_change.json.thermal_panel`，`V1_dashboard_full.png`） |
| 换流结果与选择一致、立即生效 | ❌ | 选择 `dog_ptz` 后 `PATCH /videos/1` **200**，库中 `stream_name="dog_ptz"`；但该流健康检查 `ok:false TimeoutError`，页面把画面隐藏；同时 `GET /videos/streams/stats` 仍显示 `video_id=1, viewers=1, running=true`，旧流没有断开（`dashboard_video.json.switch`，`V3_after_switch.png`）。换流逻辑没有触发 MJPEG 重连，目标流健康时也会继续显示旧画面，见 P2-2 |
| 修改地址后重连 | ❌ | 在热红外面板点“更换地址”，弹窗标题却是“改「充电房-可见光」的地址”；填入不可达 `rtsp://admin:***@127.0.0.1:1/none` 保存：PATCH **200**，提示“地址已保存，正在重连…”，库 URL 已改，但可见光画面仍持续出帧、健康检查仍 `ok:true`（原 `stream_name=camera_02` 优先于 URL），没有任何重连（`url_change.json.bogus_save/after_bogus`，`U2/U3`）。随后已恢复真实地址。见 P1-2、P2-3 |
| 只填 URL、不填 stream_name 的相机 | ❌ | 新建测试相机 id=5（`stream_name=""`，URL 为真实可用地址）：无论改前/改后，健康检查始终 `ok:false, reason="未配置视频流"`，无法预览（`address_change.json.health_initial/health_restored`，`A1/A2_bad_address.png`）。测试相机已删除 |
| 无人观看自动停转码 | ✅ | 关闭首页 32s 后 `/videos/streams/stats` 返回 `[]`，系统状态页显示“当前没有转码进程（没人看视频时会自动停）”（`dashboard_video.json.stats_after_close`，`V4`） |

### 6. 系统状态页

| 检查项 | 结论 | 证据 |
|---|---|---|
| 三张表与接口一致 | ✅ | 页面 3 张表与 `/robots/runtime`、`/videos/streams/stats`、`/sensor-gateways/runtime` 逐字一致：设备 1 在线/0 秒、设备 2/3 离线及错误；流 `#1 观众 1 运行中 0.1 秒`；网关 1/2 失败及原因（`dashboard_video.json.system_status_dom_while_watching/system_status_api`，`V2`） |
| 转码进程数随观看者变化 | ✅ | 有观众时 stats 有 1 条 `running:true`；关闭页面 32s 后 stats 变 `[]`，页面同步变为空状态（同上，`V4`） |

### 7. 设置

| 检查项 | 结论 | 证据 |
|---|---|---|
| SLA 矩阵 JSON 可编辑、可保存 | ✅ | 文本框显示 `{"P1":20,"P2":120,"P3":480,"P4":1440}`；把 P1 改 25 后 `PUT /api/v1/settings` **200**，库 `version 1→2`，审计 854；故意写坏 JSON 显示“JSON 格式不对（这一项不会保存）”、保存按钮禁用、库不变；再改回 20，库 `version 3`，审计 855（`settings_devices.json`，`S1/S2/S3`） |
| 空闲退出值生效 | ❌ | 值能保存（`security.idle_minutes` 版本到 4），但到点不退出，见 1.3 / P1-1 |

### 8. 报表

| 检查项 | 结论 | 证据 |
|---|---|---|
| Excel 5 个 sheet 与页面内容一致 | ✅（主体数字） | 真实点击下载 `巡检报表_2026-10-21_2026-10-27.xlsx`，18,233 字节；sheet 为 `概览/告警明细/环境/响应闭环/运行`，行数 17/207/13/10/7。页面、接口、Excel 均为：告警 206、严重 173、提醒 33、已确认 8、已处置 5、已关闭 7、确认率 3.9%、关闭率 3.4%、平均确认 757.5 分钟、平均关闭 866.1 分钟、在线率 89.8%、里程 18047.4m（`reports_check.json`，`R1`） |
| Excel 公式注入防护 | ✅ | 告警 206/207 的消息原为 `=cmd\|' /C calc'!A0 ...`；导出后在 E206/E207 变成前缀单引号的字符串，openpyxl `data_type="s"`，不会作为公式执行（`reports_check.json.injection_cells`） |
| 响应闭环 sheet 完整复刻页面 | ❌ | 页面有“SLA 按期销号 2.8%（4/143）”，Excel“响应闭环”只有 9 行，缺少 SLA 行（`reports_check.json.response_sheet`），见 P3-1 |
| SLA 按期率与工单 `due_at` 一致 | ❌ 口径错误 | 页面/接口/库算术一致：`4/143=2.8%`；但 143 张已关闭工单中有 **139 张 `due_at` 为 NULL**，被当成“未按期”计入分母；真正有 SLA 时限的 4 张全部按期，按有期限工单算应为 `4/4=100%`（`reports_check.json.sla_db`）。见 P2-5 |

---

## 新发现问题（按严重度，给复现步骤）

### P0-1 严重告警不再自动建工单：`ensure_from_alarm` 抛 `NameError`，异常被吞

**影响**：新产生的 P1/P2 严重告警没有关联工单 → 没有 SLA 到期时间 → 不会超期升级；“异常自动进工单”核心闭环失效。告警本身仍会显示，所以很容易被漏掉。

**证据**：
- `server/app/services/work_orders.py:43` 使用 `sla.due_at(...)`，但模块只 `from app.models.inspection import WorkOrder`，没有导入 `sla`。
- 运行时验证：`'sla' in work_orders.__dict__` 为 `False`；用桩 DB 调用 `ensure_from_alarm` 直接得到 `NameError: name 'sla' is not defined`。
- `server/app/services/alarms.py:306-311` 与 `353-359` 两处都用 `except Exception: pass` 包住建单，错误不会进日志。
- 库中告警 206/207（`env_gas_13_critical`, P1, 2026-10-27 14:05/14:06）关联工单数均为 0；而 10-23 及以前的 158 条 critical 告警有关联工单。

**复现**：
1. 触发一条 critical 告警（或直接调用 `ensure_from_alarm`）。
2. 查 `work_order where source='alarm' and source_id=<新告警 id>`，结果为空。
3. 在 `server/` 下执行 `python -c "from app.services import work_orders; ..."`，可见 `NameError`。

**建议修**：`from app.services import sla`；把 `except Exception: pass` 改为至少 `log.exception`，建单失败必须可观测；补一条“critical 告警 → 工单存在”的自动化测试。

### P1-1 空闲自动退出只“探活”不退出，设置形同虚设

**影响**：值班大屏无人操作也不会锁屏/退出，任何人回来仍可操作；安全设置给了错误的安全感。

**证据**：`web/src/composables/useIdleSession.ts:45-54` 在空闲达到阈值后只调用 `api.me()`；服务端 JWT TTL 为 240 分钟（`server/app/core/config.py:24`），所以 `/auth/me` 返回 200，前端不做任何清理。实测把 `security.idle_minutes=1` 保存后，75s 仍停留在 `/dashboard`，58s 的 `/auth/me` 为 200。

**复现**：
1. 设置 → 空闲退出改为 1 分钟 → 保存。
2. 停在驾驶舱，不碰鼠标键盘 75s。
3. 仍可点击操作；`/auth/me` 200；没有跳登录。

**建议修**：空闲到点时主动调用登出接口/触发 401 流程并清理本地状态，而不是只问“我还登录着吗”；同时补一条 1 分钟空闲的浏览器测试。

### P1-2 修改视频地址提示“正在重连”，实际不重连；有 `stream_name` 时 URL 根本不参与播放

**影响**：现场换相机 IP/地址后，页面提示成功但画面还是旧流，运维会以为已经切换；故障排查会被误导。

**证据**：
- 在首页热红外面板点“更换地址”，把设备 1 的 URL 改为 `rtsp://admin:***@127.0.0.1:1/none`：`PATCH /api/v1/videos/1` **200**，toast“地址已保存，正在重连…”，库中 URL 已变，但画面继续出帧、`/videos/health` 仍 `ok:true`，`/videos/streams/stats` 仍 `viewers=2, running=true`（`url_change.json`）。
- `server/app/api/v1/videos.py` 的 `mjpeg`/`snapshot` 优先使用 `_rtsp_for_stream(stream_name)`，`stream_name` 存在时 `v.url` 不参与播放。
- `web/src/pages/Dashboard.vue:179-183` 的 `liveSrc` 只依赖 video id 和 ticket，保存 URL 后既没有改 ticket，也没有重建 `<img>` 连接。

**复现**：
1. 首页 → 热红外/可见光面板 → 更换地址。
2. 填一个明显不可达的 RTSP 地址并保存。
3. 观察 toast、库 URL、画面和 `/videos/health`：URL 变了，画面和健康状态不变。

**建议修**：明确“地址”和“go2rtc 流”的唯一事实来源；保存后让后端重建对应流（或删除旧流）并让前端 bump ticket 重连；如果 `stream_name` 存在时 URL 无效，应在 UI 明确提示“该相机由 go2rtc 流名驱动，改 URL 不生效”。

### P1-3 设备 1 “读一次状态”返回缓存空壳，在线被显示为离线

**影响**：主设备恰是用户最常测的那台；页面提示“离线”而系统状态页显示“在线”，现场会误判设备掉线。

**证据**：`server/app/api/v1/devices.py:306-307` 对 `device_id == 1` 直接返回 `{"source":"cache","data":cache.as_dict()}`，不区分缓存是否为空/过期。实测 0.08s 返回 `data` 全空、`age_s=-1.0`、`online=false`，toast“JCROB-01：-1 秒前 · 离线”；同一时刻 `/robots/runtime` 为在线、年龄 0.369s（`settings_devices.json.devices`）。

**复现**：
1. 设备管理 → JCROB-01 → “读一次状态”。
2. 对比提示与“系统管理 → 系统状态”的设备运行表。

**建议修**：缓存为空或年龄超过阈值时回落到实时探测；或返回 `source=cache` 时不要用空数据推导 `online=false`，至少显示“无缓存快照”，并用 `/robots/runtime` 的真实在线状态兜底。

### P2-0 关闭告警只联动第一张工单（代码缺陷，当前数据未做破坏性复现）

**影响**：同一告警存在两张未关闭工单时，告警关闭后仍有一张挂着，继续占 SLA/升级队列，形成“告警已闭环、工单未闭环”的脏数据。

**证据**：`server/app/api/v1/alarms.py:39-56` 的 `_sync_order` 使用 `.first()`，只改一张。告警 195 确实有工单 160（closed）和 161（open），但 161 的 `created_at=2026-10-23 14:35:38` 晚于告警关闭时间 `14:31:48`，所以这组历史数据**不能**证明关单时漏关；本轮告警 194 只有一张工单 163，联动成功。此条是代码审查发现，需在测试环境补“两张工单+关单”验证。

**复现**（建议在测试库做）：
1. 给同一条告警建两张未关闭工单。
2. 关闭告警。
3. 查 `work_order`：按当前代码只第一张变 `closed`，其余仍 `open`。

**建议修**：把 `.first()` 改为 `.all()` 遍历关闭所有未关闭关联工单；同时补 `work_order.close` 联动审计。

### P2-1 首页告警环形图被 `limit=200` 截断，且首屏约 5–9 秒显示 0

**影响**：大屏最显眼的“告警总数”比真实值少；刚打开时显示 0，容易被当成“没有告警”。

**证据**：
- `web/src/api/index.ts:475-476` 固定 `/alarms?limit=200`；`web/src/stores/robot.ts:43-45` 直接用 `items`，丢掉 `total`；`Dashboard.vue:465-466` 用 `robot.alarms.length` 算总数。
- 库/接口/面板标题 206，环形图 200；库/接口未确认 198，环形图 195。
- `ALARM_EVERY=5`、`POLL_MS=1000`，首次刷新在约 5s 后；2s 时环形图 0/0，9s 才是 200。

**复现**：
1. 打开 `/dashboard`，2s 内看环形图为 0；9s 后看总数 200，而标题“近7日 206 条”。
2. 对比 `/api/v1/alarms?limit=1` 的 `total=206`。

**建议修**：接口单独返回按状态聚合的 total/unacked（或使用 `/alarms/kpi`/`/alarms/stats` 的 7 天聚合），不要用列表长度；首屏立即拉一次。

### P2-2 “换流”不重建 MJPEG 连接，旧流继续跑

**影响**：切换后页面可能仍显示旧画面（目标流健康时），同时旧转码进程继续占资源；用户以为已经切走。

**证据**：`chooseStream()` 只 PATCH 并刷新列表/健康，不调用 `reconnectLive()`；`liveSrc` 仍为同一个 `/videos/1/mjpeg?t=0`。实测切到 `dog_ptz` 后库已变、页面因健康失败隐藏画面，但 stats 仍 `video_id=1, viewers=1, running=true`（`dashboard_video.json.switch`）。

**复现**：
1. 首页 → 换流 → 选另一路（最好两路都健康）。
2. 观察画面是否立刻变为新流；查 stats 旧流是否仍在。

**建议修**：切换成功后 `liveTicket[id]++` 强制 `<img>` 重新请求，并让后端在流名变化时停止旧流；健康失败时也要明确停旧流。

### P2-3 热红外面板的“更换地址”实际编辑可见光相机

**影响**：用户在热红外区域操作，改的是另一台相机，容易改错生产配置。

**证据**：`Dashboard.vue:730` 热红外面板按钮调用 `openUrl(visibleVideo)`。实测点击热红外面板仅有的“更换地址”，弹窗标题为“改「充电房-可见光」的地址”，保存后改的是视频 1（`url_change.json.dialog_title_from_thermal_button`）。

**复现**：
1. 首页热红外面板（无热像设备时）点“更换地址”。
2. 看弹窗标题和保存后的 PATCH 目标。

**建议修**：无 `thermalVideo` 时隐藏/禁用该按钮；有 thermal 时传 `thermalVideo`。

### P2-4 P4 优先级结构性不可达

**影响**：需求要求 P1–P4 展示，实际只能产生 P1/P2/P3；SLA 里的 P4=1440 分钟永远不会被用到。

**证据**：`server/app/services/alarms.py:55-63` 只把 critical→P1/P2、warn→P3，其余→P4；但系统告警 `level` 只有 `warn/critical`。库中 P1=18、P2=154、P3=34、P4=0（另有 1 条 P3 critical）。

**复现**：任意产生告警，查 `alarm_record.priority`，不会出现 P4。

**建议修**：明确 P4 的业务来源（如 info/提示级指标），或在 UI/需求上把 P4 标为“预留”；不要留一个永远不出现的筛选/图例。

### P2-5 报表 SLA 分母把 139 张无时限工单算成“未按期”

**影响**：页面显示 2.8% 按期率，但真正设置过 SLA 的 4 张工单全部按期；对外汇报会严重低估履约水平。

**证据**：`server/app/api/v1/reports.py:295-297` 用全部 `closed_orders` 作分母；独立查库：7 天内工单 163、已关闭 143、其中 `due_at IS NULL` 139、有 `due_at` 且按期 4。页面/接口/Excel 均显示 `4/143=2.8%`（`reports_check.json.sla_db`）。

**复现**：
1. 打开 `/reports` 看“SLA 按期销号 2.8%（4/143）”。
2. 查 `work_order`：143 张已关闭里 139 张 `due_at` 为空。

**建议修**：分母只取 `closed_at IS NOT NULL AND due_at IS NOT NULL`，无时限工单单独显示“未设 SLA N 张”；或明确把无时限视为“不参与考核”。

### P2-6 只填 RTSP URL 的相机永远“未配置视频流”

**影响**：新增相机只填地址时无法预览/体检，用户会以为地址错误；实际是播放链路只认 `stream_name`。

**证据**：测试相机 id=5，`stream_name=""`，URL 为真实地址；`GET /videos/health` 始终 `ok:false, reason="未配置视频流"`，改 URL 前后一致（`address_change.json`）。相机已删除。

**复现**：设备管理 → 摄像头 → 新建，只填 URL、不填流名 → 保存 → 预览/健康检查。

**建议修**：URL 模式回落 ffmpeg 探测，或在表单里把 `stream_name` 设为必填并解释其与 go2rtc 的关系。

### P2-7 巡检计划没有“新建”入口，且编辑弹窗重复渲染

**影响**：需求“创建→编辑→删除”在 UI 上无法闭环，只能调 API 建计划。

**证据**：`web/src/pages/Inspection.vue` 只有编辑/删除按钮；`planEdit` 弹窗在 238 行和 281 行出现两份相同 `v-if` 块，编辑时可能叠两层。API 创建已单独验证通过（见 3）。

**复现**：打开 `/inspection`，找“新建计划”按钮：不存在；用 API 建计划后才可编辑/删除。

**建议修**：补一个新建按钮复用现有表单（`planEdit=null` 时 POST）；删掉重复的弹窗块。

### P3-1 Excel“响应闭环”缺 SLA 行

**证据**：页面有“SLA 按期销号 2.8% / 4/143”，Excel sheet 只有 9 行、无这一项（`reports_check.json.response_sheet`）。修 P2-5 时一并补上。

### P3-2 报表按设备统计出现“设备 #0”

**证据**：环境告警 206/207 的 `robot_id=NULL`，报表 `by_robot` 用 `a.robot_id or 0`，页面显示“告警 · 设备 #0 2”（`reports/summary.alarms_by_robot`）。应显示“未绑定设备/环境传感器”，不要伪造 0 号设备。

### P3-3 审计缺口

- 搁置到期自动清理没有审计（只清字段）。
- 告警关闭联动工单关闭没有 `work_order.close` 审计（只有 `alarm.close`）。
- 巡检计划更新/删除审计参数为 `NULL`。
- `ensure_from_alarm` 的异常被吞，日志也没有。

### P3-4 健康检查顶层 `ok` 与明细矛盾

**证据**：测试相机只有一路且 `videos[0].ok=false`，但响应顶层 `ok:true`（`address_change.json.health_initial`）。调用方若只看顶层会误判全部正常。

---

## 数据一致性抽查（页面 vs 接口 vs 库）

| 项目 | 页面 / UI | 接口 | 数据库 | 结论 |
|---|---|---|---|---|
| 告警总数（7 天） | 标题 206；环形图 200；首屏 2s 为 0 | `/alarms?limit=1` total=206；`/alarms/stats?days=7` total=206 | `count(*)=206` | ❌ 环形图被截断/延迟 |
| 未确认告警 | 环形图 195；铃铛 195 | `/alarms?limit=1&status=unacked` total=198 | `acked_at IS NULL` = 198 | ❌ 少 3 条（limit 200 内 5 条已确认） |
| 24h KPI | P1/P2/P3 2/0/0；未确认/未关闭 2/2 | `/alarms/kpi?hours=24` total=2, P1=2, unacked=2, open=2 | 206/207 两条 P1 未关闭 | ✅（24h 口径自洽） |
| 告警 194 / 工单 163 | 194 已关闭并显示“工单163” | `POST /alarms/194/close` 200；`/alarms/194` closed | 194 `closed_at=14:17:52`；163 `closed_at=14:17:52.521813`，resolution 含“来源告警已关闭（联动）” | ✅ 单工单联动 |
| 告警 195 / 工单 161 | — | 告警 195 已关闭 | 195 `closed_at=10-23 14:31:48`；161 创建于 14:35:38、仍 `open` | ⚠️ 161 是关单后新建，不能当作漏关证据；见 P2-0 |
| 巡检计划（编辑后） | 行文本“QA-R2-巡检计划-改 / 夜班 / 3 点” | `PATCH /inspection/plans/2` 200，`point_count=3` | `items_json` 3 个对象，名称/场站/班次同步 | ✅（随后已删除测试计划） |
| 设备 1 在线状态 | 提示“-1 秒前 · 离线” | `/devices/1/status-probe` 200，`online=false`，`age_s=-1` | 同一时刻 `/robots/runtime` 在线、age 0.369s | ❌ 两个页面互相矛盾 |
| 系统状态三表 | 设备/流/网关 3 表 | `/robots/runtime`、`/videos/streams/stats`、`/sensor-gateways/runtime` | — | ✅ 逐字一致；关闭首页后 stats=[]，页面空状态 |
| SLA 设置 | 文本框 `P1=20...`；改 25 后可保存 | `PUT /settings` 200；坏 JSON 被前端拦截 | `version 1→2→3`，最终值恢复 20，审计 854/855 | ✅ |
| 空闲退出设置 | 值 1 分钟可保存（最终恢复 5） | `PUT /settings` 200 | `security.idle_minutes` 版本 4 | ❌ 值存了但不生效 |
| 报表主数字 | 206/173/33/8/5/7；3.9%/3.4%；12.6h/14.4h；89.8%；18047.4m | `/reports/summary` 同值 | 告警 206/173/33/8/5/7；工单 163 | ✅ 页面/API/Excel/库一致 |
| SLA 按期 | 2.8%（4/143） | `sla_on_time=4, sla_closed=143, rate=2.8` | 关闭 143；其中 due_at NULL 139；有 due_at 且按期 4 | ❌ 算术一致但口径错误（应为 4/4） |
| Excel sheet | 5 个：概览/告警明细/环境/响应闭环/运行 | 下载 200，18,233 字节 | 告警明细 206 条（207 行含表头） | ✅ 主体一致；响应闭环缺 SLA 行 |
| 公式注入 | — | — | E206/E207 值前缀 `'`，openpyxl `data_type=s` | ✅ 已消毒 |
| 设备 #0 | “告警 · 设备 #0 2” | `alarms_by_robot: {robot_id:0,count:2}` | 206/207 `robot_id IS NULL` | ❌ 应显示未绑定设备 |

---

## 必须修 / 建议修 / 可忽略

### 必须修（阻断验收）

1. **P0-1 告警自动建单 NameError**：导入 `sla`，异常不能静默；补 critical→WO 回归测试。
2. **P1-1 空闲退出**：到点真正登出/清会话，不是只探 `/auth/me`。
3. **P1-2/P2-2 视频地址与换流**：保存地址/换流后必须重建流与前端连接；明确 URL 与 `stream_name` 的优先级。
4. **P1-3 设备 1 状态探测**：不能拿空缓存判定离线。
5. **P2-0 告警关闭联动**：关闭所有关联未关闭工单，并审计（改 `.first()`→`.all()`）。
6. **P2-1 首页 KPI**：用聚合 total，首屏立即拉取，不能截断到 200。
7. **P2-5 SLA 口径**：分母排除 `due_at IS NULL`，或明确单列“未设 SLA”。
8. **P2-6 URL-only 相机**：健康检查/预览要支持 URL 模式，或把 `stream_name` 设为必填。

### 建议修

- P2-3 热红外面板“更换地址”改错对象（无热像时直接隐藏）。
- P2-4 P4 不可达：补业务来源或明确“预留”。
- P2-7 巡检计划新建入口 + 去掉重复弹窗 DOM。
- P3-1 Excel 响应闭环补 SLA 行。
- P3-2 报表“设备 #0”改为“未绑定设备”。
- P3-3 审计缺口（自动解除、联动关单、计划参数、建单异常日志）。
- P3-4 健康检查顶层 `ok` 语义修正。

### 可忽略 / 环境限制

- 搁置到期清理最长 60s 延迟：可接受；但应补审计。
- 手动清 cookie 后登录页没有“会话已过期”提示：不影响账号密码清空，属体验小项。
- 设备 2/3 探测 6.05s/2.3s：满足“6 秒内不挂死”，mock/不可达是环境事实。
- 系统状态页两个网关失败：当前环境未启动 Modbus/SSH 网关，页面如实反映，不是页面 bug。
- 换 URL 测试瞬间 `viewers=2` 而页面只有 1 个 `<img>`：旧 MJPEG 连接未及时释放，随 P1-2 一起修。
- 热红外两路视频无法完整验证：设备 1 名下只有一台可见光相机，热红外属于设备 2；需要在同一设备下配置第二路后再验。

---

## 测试数据与现场清理

- 新建并删除：巡检计划 id=2、测试相机 id=5。
- 视频 1 的 `stream_name` 已从 `dog_ptz` 恢复为 `camera_02`；URL 已恢复为原地址（仅掩码展示，未在报告中输出密码）。
- SLA `alarm.sla_minutes` 已恢复 P1=20（version 3）；空闲退出已恢复 5。
- 告警 194 被本轮关闭并联动关闭测试工单 163（工单保留，状态 closed）；告警 206/207 未改动。
- 未删除任何核心数据，未重启服务。
- 并发说明：测试期间另一进程在 14:03–14:15 修改了工作区（`main.py`、`services/alarms.py`、`services/work_orders.py` 等）并生成 206/207；本报告以 14:13:39 启动的后端实例为准，未回滚他人改动。

---

## 总结（20 行内）

1. 第二轮 8 个重点全部用真实点击 + 接口 + 库做了交叉验证；单点修复多数成立。
2. 搁置必填原因、到期自动解除、单工单关闭联动、巡检点位编辑、SLA JSON、系统状态页、Excel 5 sheet 与注入消毒均通过。
3. **P0**：严重告警自动建工单因 `sla` 未导入直接 `NameError`，且被 `except: pass` 吞掉；206/207 两条 P1 无工单，核心闭环失效。
4. **P1**：空闲退出设置只探活不退出，1 分钟设置 75s 后仍在线。
5. **P1**：改视频地址/换流不重建连接；有 `stream_name` 时 URL 根本不参与播放，toast“正在重连”是假的。
6. **P1**：设备 1 读状态 0.08s 返回空缓存并判离线，与系统状态页“在线”矛盾。
7. **P2**：关闭告警代码只联动第一张工单（`.first()`），重复工单场景存在漏关风险；195/161 是关单后新建，未作为实证。
8. **P2**：首页环形图被 `limit=200` 截断（200 vs 206），首屏 5–9s 还是 0。
9. **P2**：SLA 报表把 139 张无 `due_at` 工单算作未按期，显示 2.8%，实际有期限的 4/4 全按期。
10. **P2**：P4 结构性不可达；URL-only 相机永远“未配置视频流”；热红外“更换地址”改的是可见光。
11. **P2**：巡检计划没有新建 UI；Excel 响应闭环缺 SLA 行；“设备 #0”是未绑定设备被伪造成 0 号。
12. 环境限制：设备 1 名下只有一路视频，热红外属于设备 2，两路同屏实时无法完整验收；网关失败是环境未启动。
13. 结论：**不建议直接验收通过**；先修 P0-1、3 个 P1 与 P2-0，再复测告警自动建单、空闲退出、换流/改址、设备探测、重复工单联动。
14. P0-1 修复量很小（补一行 import + 日志），但影响最大，应作为第一优先。
15. 完整证据与截图在 `%LOCALAPPDATA%\Temp\qa_r2\`，测试数据已清理，服务未重启。
