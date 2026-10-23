# 防爆机器人智能巡检平台 · 端到端验收报告

- 测试时间：2026-10-23 13:20–14:45
- 环境：前端 `http://127.0.0.1:5173`，后端 `http://127.0.0.1:8000/api/v1`，SQLite `server/data/app.db`（WAL）
- 账号：`admin/admin123`；另建 viewer / operator / safety / auditor 临时账号做越权与流程测试
- 方法：Playwright 真实浏览器点击 + 抓 `response`（URL/方法/状态码）+ 调 API / 查库交叉验证 + 关键代码定位
- 证据：截图在 `docs/reviews/qa-evidence/claude-full-qa/`，原始 JSON/脚本在 `C:/Users/17591/AppData/Local/Temp/qa_full/`
- 覆盖：32 个路由，约 1100 个可见按钮（绝大多数是列表行内同构按钮），去重后约 150 类操作；**未实际点到的项一律标 ⚪，不�报告已写入 `docs/reviews/claude-full-qa.md`（含 6 个指定章节 + 测试现场说明）。

**核心结论**
- ✅ 真闭环：登录/锁定/强制改密/退出回跳、RBAC、TOTP 登录、告警判级与关闭、告警→审计、巡航状态机与 step 落库、并发/写锁保护、外设增删→能力接口、报表 xlsx/CSV、通知/密钥/模板。
- ❌ P0：只要展开“双因子认证”菜单就会静默轮换 TOTP 密钥，旧码立即失效且新密钥不展示，用户被锁死。
- ❌ P0：TOTP 验证无失败计数，连续 10 次错误码不限速。
- ❌ P0：删除账号不清理密码历史，SQLite 复用 ID 后新账号首次改密报 `PASSWORD_REUSED`。
- ❌ P1：告警 195 关闭后，关联工单 160 仍是待派单，告警页与工单页口径冲突。
- ❌ P1：报表环境超限只认传感器阈值、不认外设规则——SF6 有 16 条 ≥80 告警，xlsx 仍显示 `over=0`。
- ❌ P1：新增传感器无 `robot_id`，`/sensors?robot_id=1` 查不到，首页/设备页成孤儿数据。
- ❌ P1：首页热红外面板 `|| true` 永真、环境面板无 `v-if`；添加 speaker 后能力有 `audio.tts`，首页却没有语音面板。
- 💬 P1：“全部标为已读”只写 localStorage，服务端未读数和首页角标不变。
- ❌ P1：21 条告警 `robot_id=NULL`，报表出现“0 号机器人”。
- ❌ P1：单点下发只到 `running`，无完成轮询；30s 后看门狗建 critical 告警+工单，状态机缺 `done` 段。
- ❌ P2：SF6 被标成“可燃气体/%LEL”、告警数值 `111.80000000000001ppm`、三角色显示“未知角色”。

**范围与清理**
- 覆盖 32 个路由、约 1100 个可见按钮（去重约 150 类操作）；未点到项均标 ⚪，未把“页面能打开”算作闭环。
- 已清理本次测试账号/外设/密钥/通知/模板；恢复写锁关闭、温度阈值 50/60；保留 task run 7–13、告警 192–195、工单 160 作证据。
- 未重启服务、未删除核心数据、未改 admin 密码。
误提示“动态码不正确”，正确进首页 | 30s/6 位、±1 窗口 | ✅ |
| 11 | TOTP 关闭 | `/auth/totp/disable` 200 | 状态回到未开启 | 再次登录只需密码 | ✅ |
| 12 | viewer 访问账号管理 | 打开 `/users` | 跳 `/robot-status?denied=1` | 管理接口 401/403 | ✅ |
| 13 | 审计留痕 | — | — | `operation_log` 有 `auth.login`、`auth.login_failed`、`user.create/delete`、`alarm.close` 等真实记录 | ✅ |

### 安全缺陷（必须处理）

1. **❌ P0：只要打开“双因子认证”菜单，就会静默轮换 TOTP 密钥，用户被永久锁在门外。**
   - 复现：开启 TOTP → 退出 → 用密码+动态码登录 → 点右上角用户菜单里的“双因子认证”（不点任何按钮）。
   - 证据：`POST /auth/totp/start` 返回 200 且 `secret_changed=true`；旧 authenticator 的动态码随后 `POST /auth/login` → 401 `TOTP_INVALID`；等 30s 用新密钥生成的码 → 200。前端在“已开启”状态下从不展示新密钥。
   - 代码：`server/app/api/v1/auth.py` 的 `totp_start` 无条件 `totp_secret()` + 写库；`web/src/components/UserMenu.vue` 的 `openTotp()` 每次展开菜单都调 `api.totpStart()`。
   - 影响：普通用户误点一次即失去登录能力，只能管理员重置。
2. **❌ TOTP 验证无失败计数/锁定。** 密码正确、动态码连续错 10 次，全部 401 `TOTP_INVALID`，没有限速、没有锁定；登录锁定只覆盖密码路径。
3. **❌ 删除账号不清密码历史，SQLite 复用 ID 后新账号“首次改密”被拒。**
   - 复现：建临时用户（id=21）→ 删除 → 新建用户拿到同一 id → 首次改密返回 `PASSWORD_REUSED`。
   - 证据：`delete_user` 只 `db.delete(user)`；`PasswordHistory.user_id` 无 FK/级联。当前库仍有 8 条孤儿历史（user_id 3–6，属历史遗留，未清理）。
   - 影响：新用户可能无法设置自己的密码；也属于账号生命周期数据不完整。
4. **❌ 角色显示不全。** `UserMenu.vue` 的 `ROLE_TEXT` 只映射 admin/safety/operator/viewer，`sysadmin/secadmin/auditor` 显示“未知角色”。
5. **⚪ 未验证项**：CSRF 缺失/错误时的拒绝、会话空闲超时、并发会话列表与踢出、Cookie 的 Secure/SameSite 细节、TOTP 重放（代码有 `totp_last_step`，但未做跨窗口重放实测）。

---

## 页面 × 按钮矩阵

说明：列表页大量按钮是同一行模板重复（如告警行 ✓/✎/工单/⏹/⟲），表内按“同构按钮”抽样点击并说明；未点到的子按钮明确记 ⚪。判定看的是“有没有真请求 + 数据有没有真变 + 前端是否反映”。

| 页面 | 按钮/操作 | 请求证据 | 结果 / 数据变化 | 判定 |
|---|---|---|---|---|
| `/login` | 登录、错密码、锁定、强制改密、TOTP 开关 | 见上节 | 全链路真实 | ✅ |
| `/dashboard` | 加载看板 | `GET /alarms/stats`、`/alarms`、`/sensors?robot_id=1`、`/robots/1/capabilities`、`/dashboard/feed` 均 200 | 194 总/188 未确认/6 已确认与 `/alarms/stats` 逐项一致；6 点位、1 传感器也一致 | ✅ |
| `/dashboard` | 热红外“打开全屏页” | 无请求 | 无热红外流时按钮 disabled | ⛔ |
| `/dashboard` | 云台/车体控制、锁定屏幕、消息 tab | — | 未逐项点击 | ⚪ |
| `/robot-status` | 页面加载 | `/robots/1/status` 200，数据年龄 0.7s | 实时状态正常 | ✅ |
| `/map` | 加载地图/点位 | `/robots/1/map/current`、`/map/png`、`/nav-points` 200 | 地图与点位渲染 | ✅ |
| `/map` | 新增点位 / 退出打点 | 无请求 | 未进入打点模式，按钮 disabled | ⛔ |
| `/map` | 导入 | — | 未点击 | ⚪ |
| `/video`、`/room` | 测试连通 / 刷新列表 / 摄像头配置 | — | 仅验证页面与 MSE 流加载 | ⚪ |
| `/env` | 加载趋势 | `/sensors?robot_id=1` 200 | 展示传感器与阈值 | ✅ |
| `/env` | 去标定传感器 | — | 未点击跳转 | ⚪ |
| `/tasks` | 查询/重置/新建任务/下发/暂停/继续/取消 | — | 机器人镜像任务，未逐项操作 | ⚪ |
| `/inspection` | 生成任务/刷新/详情/手机打卡/完成 | — | 仅验证移动端页面可打开（截图 mobile-m-task-1 / mobile-task-calendar） | ⚪ |
| `/work-orders` | 派单 → 处理 → 复核 → 关闭（160/161 条，行内按钮同构） | `POST /work-orders/160/assign`、`/processing`、`/review`、`/close` 均 200；审计 670–673 | WO160 状态真实推进到 `closed`，`closed_at` 落库 | ✅ |
| `/work-orders` | 📱（手机端处理入口） | — | 未点击 | ⚪ |
| `/task-runs` | 从模板生成计划 | `POST /task-runs` 200 | 新 run 状态 `planned` | ✅ |
| `/task-runs` | 巡航 | `POST /task-runs/12/dispatch` 200 → 轮询 | run12：`planned`(0s)→`running`(1s)→`done`(6s)；step `ok`，result `{"point":"QA验收点B-142322","x":-2.865,"y":-2.889,"action":"wait","waited":3}` 落库 | ✅ |
| `/task-runs` | 巡航失败分支 | run7 | 3s 后 `failed`，错误“机器人报完成但离目标 1.7m（该点位要求 1.0m 内）”，失败原因落库 | ✅（失败也真实持久化） |
| `/task-runs` | 单点下发 | `POST /task-runs/8/dispatch` 200；`/13/dispatch` 200 | 只到 `running`，12s 后仍 running，step 仍 pending；无平台侧完成轮询，等机器人 `POST /task-runs/ingest` 才会 done | ❌ |
| `/task-runs` | 暂停 / 继续 | `POST .../8/pause` 200、`/resume` 200 | `paused=true` → `false`，状态仍 running（暂停不是独立状态） | ✅（与设计一致） |
| `/task-runs` | ✕ 取消（强制原因） | `POST /task-runs/13/cancel` 200 | `cancelled`，原因落库；空原因不会发请求（先弹 prompt） | ✅ |
| `/task-runs` | 并发下发保护 | 另一次下发 → 409 `RUN_ACTIVE` | 前端提示，未产生重复 run | ✅ |
| `/task-runs` | 写锁下下发 | `POST /task-runs/9/dispatch` 403 `WRITE_LOCKED` | toast“写操作未开启…”，run 保持 `planned` 且 `dispatch_error` 落库 | ✅（错误处理真实） |
| `/task-runs` | 30s 看门狗 | 定时任务 | 单点 run 8 无回传 → 生成 critical 告警 195，并自动建工单 160 | ✅（机制真实；但见下方“单点无完成路径”） |
| `/task-templates` | 复制 | `POST /task-templates/{id}/copy` 200 | 出现“副本”行 | ✅ |
| `/task-templates` | 删除副本 | `DELETE /task-templates/{id}` 200 | 行消失 | ✅ |
| `/task-templates` | 下发（列表行） | 无请求 | 按钮 disabled | ⛔ |
| `/task-templates` | 编辑 ✎ / 新建模板 | — | 未点击 | ⚪ |
| `/points` | 同步到机器人 | 无请求 | disabled（“只读：新增/修改点位要写机器人”） | ⛔ |
| `/points` | 查询/重置/去地图打点 | — | 未点击 | ⚪ |
| `/alarms` | 关闭告警 | `POST /alarms/195/close` 200；审计 `alarm.close` 630 | 告警 `closed_at` 落库，闭环数 6 | ✅ |
| `/alarms` | 确认 ✓（告警 192/193） | `POST /alarms/{id}/ack` 200 | `acked_at` 落库 | ✅ |
| `/alarms` | ✎ 编辑 / 工单 / ⏹ / ⟲（行内同构） | — | 抽样未点全 | ⚪ |
| `/alarms` | 查询/重置/刷新/导出 CSV | — | 未逐项点击 | ⚪ |
| `/ai-results` | 刷新/算法筛选 | — | 仅加载列表 | ⚪ |
| `/alarm-rules` | 去修改阈值 / 刷新告警状态 | — | 未点击 | ⚪ |
| `/history/tasks`、`/history/alarms` | 任务记录/告警记录 tab、刷新、导出 CSV | `GET /history/alarms/export.csv` 下载 | CSV 195 行（1 表头+194 告警），列头正确，与实际列表一致 | ✅ |
| `/history/*` | 重置 | — | 未点击 | ⚪ |
| `/reports` | 统计 | `GET /reports/summary?days=7` 200 | 194 告警/161 工单/已闭环 6，与库一致 | ✅ |
| `/reports` | 导出 Excel | `GET /reports/export.xlsx` 200 | xlsx 5 个 sheet：概览/告警明细/环境/响应闭环/运行；明细 194 条 | ✅ |
| `/reports` | 打印 / PDF | 打开 `/reports/print` | 打印页正常渲染 | ✅ |
| `/run-data` | 刷新 | — | 仅加载 | ⚪ |
| `/robots` | 新增/编辑/切换适配器/删除 | — | 仅加载；删除 robot1 disabled | ⛔/⚪ |
| `/peripherals` | 添加外设（speaker） | `POST /peripherals` 200；审计 657 | 生成外设行；`capabilities/panels` 出现 `audio.tts` | ✅（后端能力同步） |
| `/peripherals` | 删除外设 | `DELETE /peripherals/11` 200；审计 659 | 外设行消失；`audio.tts` 从能力接口消失 | ✅ |
| `/peripherals` | 规则 / 停用 | — | 未点击 | ⚪ |
| `/cameras` | 新增/播放/编辑/测试/切换/暂停/删除/大屏 | — | 仅加载 | ⚪ |
| `/sensor-gateways` | 新增网关 / 测试 / 删除 | — | 仅加载 | ⚪ |
| `/env-device` | 新增传感器 | `POST /sensors` 200 200 | 列表出现；但 `/sensors?robot_id=1` 不含它，无法绑定机器人 | ❌ |
| `/env-device` | 修改阈值 | `PATCH /sensors/3` 200；审计 494/499 | 50/60 → 30/45；推 35 → warn（消息“≥30”）、推 50 → critical（“≥45”）；恢复 50/60 | ✅ |
| `/env-device` | 🗑 删除传感器 | — | 未点击（测试传感器走 API 清理） | ⚪ |
| `/record/plan` | 开始录制 / 新增计划 | — | 未点击；停止 disabled | ⚪/⛔ |
| `/record/playback` | 查询/播放/删除 | — | 仅加载 | ⚪ |
| `/messages` | 全部标为已读 | **无请求** | 只写 `localStorage.jc_msg_read_ts`；刷新后服务端未读数与首页角标不变 | 💬 |
| `/messages` | 查看 | — | 未点击 | ⚪ |
| `/users` | 新建账号 | `POST /users` 200 | 新账号出现，密码哈希存储；首次登录强制改密 | ✅ |
| `/users` | 删除账号 | `DELETE /users/{id}` 200；审计 680–685 | 账号消失（但密码历史残留，见 P0-3） | ❌（部分） |
| `/users` | 重置密码/禁用/改角色 | — | 未逐项点击 | ⚪ |
| `/settings` | 保存配置（写锁、SLA） | `PATCH /settings` 200；审计 560/663 | `robot.write_enabled=false` 真实生效；SLA P1–P4 落库 | ✅ |
| `/settings` | 撤销/重新探测/刷新 | — | 未点击 | ⚪ |
| `/notify` | 新增通道 | `POST /notify-channels` 200 | 行出现 | ✅ |
| `/notify` | 测试 | `POST /notify-channels/{id}/test` | 目标不可达时前端如实显示 `ConnectError`，没有假成功 | ✅ |
| `/notify` | 启停 / 删除 | `PATCH`/`DELETE` 200 | 状态翻转、行消失 | ✅ |
| `/oplog` | 查询/重置/下一页 | `GET /audit-logs` 200 | 每页 50 条，offset 前进，重置回第一页 | ✅ |
| `/keys` | 新建密钥 | `POST /api-keys` 200 | 明文一次显示，长度 47、前缀 `jck_`；库中只存哈希 | ✅ |
| `/keys` | 吊销 | `DELETE /api-keys/{id}` 200 | 行状态变更/消失 | ✅ |

---

## 数据不同步清单

### 已验证同步正常（先给结论）

| 链路 | 证据 | 判定 |
|---|---|---|
| 首页 KPI ↔ `/alarms/stats` ↔ `/alarms` | 194/188/6 三处一致；处置后 194/187/7 同步变化 | ✅ |
| 告警关闭 → 审计 | `operation_log` 有 `alarm.close`，target `alarm:195` | ✅ |
| 告警关闭 → 报表 | 报表闭环数 6 与库中 `closed_at` 非空数一致 | ✅ |
| 阈值修改 → 报警判级 | oplog 494 改 30/45，随后 35→warn、50→critical；消息引用新阈值 | ✅ |
| 任务巡航 → step 落库 | run12 的 step `ok` + result JSON 持久化 | ✅ |
| 外设增删 → capabilities/panels | speaker 加/删后 `audio.tts` 出现/消失 | ✅ |
| 报表/CSV 导出 ↔ 列表 | xlsx 194 条、CSV 195 行与 `/alarms` 总数一致 | ✅ |
| 写锁 → 下发 | 403 + toast + `dispatch_error` 落库，未伪造 running | ✅ |

### P0

1. **❌ TOTP 开启状态与 authenticator 状态脱节（详见登录节）**
   - 复现：开启 TOTP → 重新登录 → 只展开“双因子认证”菜单。
   - 接口证据：`POST /auth/totp/start` 200，返回新 secret；旧码 401，新码 200；UI 不展示新 secret。
   - 代码：`auth.py:totp_start`、`UserMenu.vue:openTotp`。
   - 影响：用户被锁死，属于认证状态不同步。

2. **❌ 告警关闭后关联工单仍为待派单**
   - 复现：`POST /alarms/195/close` 200 → `GET /work-orders` 查 source=alarm:195。
   - 证据：关闭时 WO160 仍 `open/待派单`，`closed_at=null`；后经 assign→processing→review→close 才闭合（审计 670–673）。
   - 影响：告警列表显示“已闭环”，工单页仍显示未处理，报表口径互相打架。
   - 建议：明确策略——关闭告警前要求工单已关，或关闭告警时级联关闭/标注工单，二者必须选一个并在 UI 说明。

3. **❌ 删除账号不清密码历史 + SQLite ID 复用**
   - 证据：新账号 id=21 首次改密返回 `PASSWORD_REUSED`；`password_history` 现存 8 条孤儿记录（user_id 3–6）。
   - 代码：`users.py:delete_user` 只删 user；`PasswordHistory.user_id` 无 FK/ondelete。
   - 影响：同一 ID 被复用时，新用户被旧密码历史挡住；账号生命周期不完整。

### P1

4. **❌ 报表“环境超限”只认传感器阈值，不认外设规则**
   - 复现：外设 2 规则 warn 50/crit 80（`config.rule`），传感器 2 自身阈值 1000/1500；推送 111.7–999。
   - 证据：产生 16 条 `env_gas_2_critical`（消息“≥80”）；导出 xlsx 环境 sheet 111 条读数、max=999，但 `over=0`、`over_rate=0`。
   - 代码：`server/app/api/v1/reports.py` 只用 `s.warn_high/crit_high` 等字段，未走 `_rule_for`/`effective_rule`。
   - 影响：报表少报环境超限，和告警中心直接矛盾。

5. **❌ 传感器不能绑定机器人，新增后从设备页/首页消失**
   - 复现：`POST /sensors` 200 → `GET /sensors?robot_id=1` 查不到；`GET /sensors`（全量）能查到。
   - 代码：`SensorIn` 无 `robot_id`，`_out` 也不返回绑定关系。
   - 影响：设备页、首页环境面板按机器人过滤时看不到新传感器；用户以为“添加成功”，实际成了孤儿数据。

6. **❌ 首页面板与 capabilities 不同步（能力开关是假的）**
   - 热红外：`Dashboard.vue:503` `v-if="hasPanel('video.thermal') || true"`，机器人 1 没有 thermal 能力也照样渲染“热红外视频”。
   - 环境面板：模板无 `v-if`，任何机器人都会出现。
   - 音频：外设添加后能力/面板注册表都有 `audio.tts`，但 `Dashboard.vue` 没有语音面板模板，页面不出现“语音喊话”。
   - 外设页 toast 仍承诺“首页面板会跟着出现”，与实际不符。
   - 影响：能力接口、外设页、首页三处口径不一致；注册表“加 kind 首页零改动”的设计目标未达成。

7. **💬 消息“全部标为已读”只改浏览器本地**
   - 证据：点击后 `localStorage.jc_msg_read_ts` 变化，**无任何 API 请求**；`GET /messages` 未读数不变，首页角标不变。
   - 影响：换浏览器/换设备未读状态回退，属于典型的前端假闭环。

8. **❌ 告警归属机器人丢失，报表出现“0 号机器人”**
   - 证据：21 条告警 `robot_id=NULL`（env_gas_1_warn 18、ai_meter 2、task_stuck 1）；报表 `alarms_by_robot` 出现 `{"robot_id": 0, "count": 21}`。
   - 其中 195 是 run8（robot_id=1）的看门狗告警，却也没写 robot_id。
   - 影响：按机器人统计/追责/报表筛选都会失真。

9. **❌ 单点下发没有完成路径，只能靠外部 ingest**
   - 复现：`POST /task-runs/8/dispatch` 200 → 12s 后仍 `running`、step `pending`；30s 后看门狗生成告警 195 + 工单 160。
   - 对比：巡航路径 `CruiseRunner` 每 3s 轮询适配器，能到 `done/failed`；单点路径只写 `running`，不轮询 `get_order`。
   - 影响：用户点“单点下发”后永远看不到完成，除非机器人主动回调；状态机 `planned→running→done` 只实现了前两段。
   - 建议：复用巡航的轮询/超时逻辑，或明确显示“已下发，等待机器人回传”，不要让人误以为卡死。

### P2

10. **❌ SF6 被归为“可燃气体”**：`KINDS["gas"]` 的 label 是“可燃气体”、单位 `%LEL`；SF6 传感器实际单位 ppm、性质不可燃。环境页分类与报警文案会误导。
11. **❌ 浮点直接拼进告警文案**：`_judge` 用 `f"{value}{unit}"`，产生 `111.80000000000001ppm`（告警 189）。建议按单位保留 1–2 位小数。
12. **❌ 角色显示“未知角色”**：sysadmin/secadmin/auditor 未在 `ROLE_TEXT` 中映射。
13. **⚠️ 单点/巡航的 mock 位姿会漂移**：run7 因“离目标 1.7m”失败。平台把失败如实落库，这点是对的；但 mock 适配器沿半径 3m 圆周移动，默认到点半径 1m，容易把测试/演示做成“随机失败”。建议 mock 支持定点或把测试半径调大。
14. **⚠️ 告警 194 的阈值文案与同时段审计不一致**：消息写“≥20”，但 oplog 当时记录的是 30/45。建议排查阈值来源（外设规则/传感器/全局默认）是否在判级时混用；当前无法从 `meta_json` 追溯（该字段为空）。

---

## 造假/空实现清单

| # | 现象 | 证据 | 判定 |
|---|---|---|---|
| 1 | “全部标为已读”说成功，服务端未读数不变 | 无请求，仅 `localStorage` | 💬 假闭环 |
| 2 | “外设已添加，首页面板会跟着出现” | speaker 加成功、能力有 `audio.tts`，首页无语音面板 | 💬 提示与事实不符 |
| 3 | 首页热红外面板永远显示 | `v-if="hasPanel('video.thermal') || true"` | ❌ 能力开关是摆设 |
| 4 | 首页环境面板无条件显示 | 模板无 `v-if` | ❌ 同上 |
| 5 | TOTP 已开启时打开菜单即换密钥 | `totp_start` 无条件写 secret，UI 不显示新密钥 | ❌ 静默破坏认证 |
| 6 | 单点下发“已下发”但永远不完成 | run8 12s 仍 running；无 ingest 就无 done | ❌ 成功只代表订单被接收，UI 未说明 |
| 7 | 报表环境超限为 0 | 111 条读数 max 999，16 条 ≥80 告警，xlsx `over=0` | ❌ 报表空实现（口径错） |
| 8 | 报表出现 0 号机器人 | 21 条告警 `robot_id=NULL` → `by_robot.robot_id=0` | ❌ 假实体 |
| 9 | 新增传感器“成功”但无法绑定机器人 | `/sensors?robot_id=1` 查不到 | ❌ 半成品 |
| 10 | 任务日历 | 页面明确显示未实现/空态（截图为占位） | ⚪ 空实现但诚实，不计造假 |
| 11 | 通知测试 | 目标不可达时返回 `ConnectError` 并如实提示 | ✅ 反面例证：没有假成功 |
| 12 | Excel/CSV 导出 | 5 sheet、195 行，与列表一致 | ✅ 真导出 |
| 13 | 审计日志 | 685 条，含登录失败、删除账号、告警关闭、工单流转 | ✅ 真落库 |

---

## 与工业级巡检平台应有能力的差距

| 能力域 | 工业级基线 | 当前实现 | 差距 |
|---|---|---|---|
| 告警治理 | ISA-18.2：主告警表、合理化、抑制/搁置、洪泛检测、按操作员统计响应 KPI | 已有 P1–P4、搁置、SLA、KPI；缺主告警清单/合理化记录、设计性抑制、洪泛检测、逐次状态迁移审计 | 中 |
| 防爆与气体检测合规 | IEC 60079 / GB 3836 区域与设备认证；气体传感器定期标定/ bump test 记录 | 有防爆资产台账，但无 Ex 标志/证书/区域字段；无传感器标定周期、标定记录、失效提醒；SF6 归类错误 | 高（行业硬门槛） |
| 功能安全/OT 安全 | IEC 62443 分区/管道、最小权限、MFA 强制、会话管理、密钥保管 | RBAC、审计、CSRF、TOTP 有；TOTP 无失败锁定且会自锁，无 SSO/LDAP、无会话列表/踢出、无 IP 白名单；摄像头 URL 含明文密码存库 | 高 |
| 身份认证 | NIST SP 800-63B：MFA、抗重放、限速、安全默认 | 有 TOTP 与重放防护代码；缺验证失败限速/锁定，MFA 非强制 | 中高 |
| 应用安全验证 | OWASP ASVS：认证、会话、访问控制、日志、输入校验 | 主要写接口有权限与 CSRF；缺统一安全测试/依赖扫描证据 | 中 |
| 机器人/车队集成 | VDA 5050 或 OPC UA 等标准接口、车队调度、任务互操作 | 单一 jcrob HTTP 适配器 + mock；无标准协议、无多机调度/充电策略 | 高 |
| 视频联网 | ONVIF 发现、GB/T 28181 接入、级联 | 手工填 RTSP，go2rtc 转 MSE；无发现/注册/级联 | 中 |
| 巡检作业 | 离线巡检、NFC/二维码防伪、照片 GPS/时间/哈希证据、路线优化、缺陷分级标准 | 有扫码打点、计划、手机端页面；缺离线、证据哈希、GPS/EXIF、路线优化 | 中高 |
| 工单/EAM | 备件、工时、预防性维护计划、停机统计、SLA 升级 | 有派单/处理/复核/关闭、SLA due_at；缺备件/工时/PM 计划/升级规则 | 中 |
| 资产全生命周期 | ISO 55000：资产台账、健康度、维护策略、成本 | 设备台账 + 适配器状态；无健康评分/维护策略/成本 | 中 |
| 数据与报表 | 定时报表、趋势/对比、数据质量标记、WORM 审计导出 | 手动统计/导出、打印；无定时、无质量标记、审计不可导出/WORM | 中 |
| 平台可靠性 | 双机/备份恢复、可观测性、时间同步 | 单机 SQLite；未见备份恢复演练、平台自监控、NTP 状态 | 高（生产化前必须） |

公开资料链接：

- ISA-18.2 告警管理：<https://www.isa.org/standards-and-publications/isa-standards/isa-18-2>
- IEC 62443 工业网络安全：<https://www.iec.ch/blog/understanding-iec-62443>
- IEC 60079 爆炸性环境：<https://www.iec.ch/explosive-atmospheres>
- NIST SP 800-63B 数字身份认证：<https://pages.nist.gov/800-63-4/sp800-63b.html>
- OWASP ASVS：<https://owasp.org/www-project-application-security-verification-standard/>
- VDA 5050（AGV/AMR 接口）：<https://github.com/VDA5050/VDA5050>
- OPC UA：<https://opcfoundation.org/about/opc-technologies/opc-ua/>
- ISO 55000 资产管理：<https://www.iso.org/standard/55089.html>
- GB/T 28181（公共安全视频联网）：<https://openstd.samr.gov.cn/bzgk/gb/>

---

## 必须修 / 建议修 / 可忽略

### 必须修（P0，放行前）

1. **TOTP 密钥轮换**：`totp_start` 在 `totp_enabled=true` 时必须拒绝或要求先验证旧码/密码；开启流程只在未启用时生成并展示一次密钥；`openTotp()` 不得在展开菜单时发 `start`。
2. **TOTP 防爆破**：动态码失败计入 `login_attempt`，复用 5 次/10 分钟锁定；锁定响应建议 429。
3. **告警↔工单一致性**：关闭告警前校验关联工单，或级联关闭并在 UI 标注；禁止出现“告警已闭环、工单待派单”。
4. **密码历史级联**：`PasswordHistory.user_id` 加 FK `ON DELETE CASCADE`（或删除用户时显式清理）；用户主键改 `AUTOINCREMENT`/UUID，杜绝 ID 复用。清理现有 8 条孤儿历史前先确认归属。
5. **报表阈值口径统一**：`reports.py` 环境统计复用 `_rule_for`/`_judge_with_rule`（外设规则优先），并在报表标注阈值来源；补一条“SF6 规则 80、传感器 1000”的回归测试。
6. **传感器绑定机器人**：`SensorIn/_out` 增加 `robot_id`，前端新增/编辑可选机器人；迁移已有传感器；列表按 robot 过滤必须能查到新建项。
7. **首页面板按能力渲染**：删掉 `|| true`，环境面板加 `v-if`；实现 `audio` 面板或从 registry/能力中移除 `audio.tts`；外设页 toast 文案与事实一致。
8. **消息已读服务端化**：新增 `POST /messages/read-all`（或按条 read），首页角标与未读数从同一接口取。
9. **告警 robot_id 归属**：`raise_external` / 看门狗 / AI 结果统一写 `robot_id`；历史 NULL 数据回填或报表归为“未归属”，不要输出 0 号机器人。
10. **单点下发完成路径**：复用巡航轮询，或在 UI 明示“等待机器人回传”；看门狗告警去重，避免每次卡住都新开 critical 告警+工单。

### 建议修（P1/P2）

1. 角色文案补全 `sysadmin/secadmin/auditor`。
2. SF6 单独建模（`kind=sf6` 或 `gas` 子类型），标签/单位不要复用可燃气的 `%LEL`。
3. 告警文案数值按单位格式化（`round(value, 2)`），避免 `111.80000000000001`。
4. 阈值判级写 `meta_json`（来源、生效阈值、规则 ID），便于追账；排查告警 194 的“≥20”来源。
5. 告警列表支持批量确认/批量关闭；工单列表支持按来源告警筛选。
6. 审计日志增加导出与保留策略；`prev_hash/row_hash` 已有，补校验任务。
7. 摄像头/网关密码进密钥库或加密存储，列表继续打码；补 ONVIF 发现。
8. 报表增加定时导出（日报/周报）与环境超限明细钻取。
9. 传感器增加标定周期、标定记录、到期提醒；防爆资产增加 Ex 标志/证书/区域字段。
10. 单点/巡航 mock 支持定点，避免演示时随机“到点失败”；到点半径可配置。
11. 移动端巡检补离线缓存、照片 GPS/时间/哈希证据。
12. 增加登录会话列表、强制下线、MFA 强制策略（按角色）。

### 可忽略（当前阶段）

1. 页面文案/间距/图标不统一等纯视觉问题。
2. 列表行内按钮未逐个点全（同构模板，抽样已覆盖写操作）。
3. 任务日历占位页——只要明确标注“未实现”，不算造假；排期实现即可。
4. 巡检/录像等只读页面的“未点击”项，在写锁和演示数据下不影响放行判断，但上线前需补测。
5. mock 适配器的位姿漂移只影响演示，不影响真机适配器契约（但建议按上条修）。

---

### 测试数据与现场状态

- 已清理：本次创建的 `qa_*` 账号（0 残留）、临时 API Key、通知通道、测试传感器、speaker 外设、测试模板/点位。
- 已恢复：`robot.write_enabled=false`；环境温度阈值 50/60；SF6 外设规则保持 50/80。
- 保留证据：task run 7–13（7 failed、8/9/10/11/13 cancelled、12 done）、告警 192–195、工单 160（已关闭）、截图与 JSON。
- 未清理：8 条历史孤儿 `password_history`（user_id 3–6，非本次产生），留作 P0-3 证据。
- 全程未重启服务、未删除核心数据、未修改 admin 密码。
