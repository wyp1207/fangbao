# 防爆机器人巡检平台 · 按钮逐一点击 + 状态同步实测报告

- 测试时间：2026-10-22 23:25 — 2026-10-23 00:25（Asia/Shanghai）
- 被测版本：`HEAD = ef31e96`（2026-10-22 23:59:26 `feat: 失败路径补全（1）+ 日志落盘 180 天（2）`）
- 运行态说明：测试期间工作树中存在并行修改（`server/app/api/v1/reports.py`、`server/app/main.py`、`server/app/services/alarms.py`，均为未提交状态），且后端被外部重启多次（PID `377908 → 341452 → 204348 → 324992`）。**本报告以实际运行到的服务行为为准，并标注了时间点。**
- 环境：前端 `http://127.0.0.1:5173`，后端 `http://127.0.0.1:8000/api/v1`，账号 `admin/admin123`
- 浏览器：Playwright 1.64 + Chromium 1243（`%LOCALAPPDATA%\ms-playwright\chromium-1243\chrome-win64\chrome.exe`），1680×950 / 1920×1000
- 约束：只读优先。没有删除业务数据、没有改既有账号密码、没有重启服务、没有提交任何写操作表单。写按钮一律只打开弹窗/下拉，不点“保存/提交/确认/删除/下发/派单/开始录制/测试”。

---

## 0. 结论速览

| 档位 | 数量 | 代表问题 |
|---|---|---|
| 必须修 | 9 项 | 告警/工单风暴、报表导出 500、20 并发可拖死整站、审计链校验失败、切换设备后状态串台、14 个已交付页面菜单标“未接入”、录像计划组件未注册、权限 UI 与后端 403 不一致、部署缺列导致报表 500 |
| 建议修 | 10 项 | 预检不校验写开关、消息角标 100 截断、首页前 5 秒告警为 0、环境读数过期无强提示、CSV 只导当前页、回放出现已删摄像头 #2、告警未关联工单、手机已完成任务仍可提交（疑似）、操作日志无自检入口、设备台账 ⇄ 无反应 |
| 可忽略 | 5 项 | 占位页文案、真机未接入提示、导出按钮打开新标签、消息中心全量渲染、导航“未接入”中真正未接入的「任务日历」 |

**一句话结论**：页面覆盖度和只读查询链路基本可用；只要不碰写操作，绝大多数列表/详情/弹窗都能打开。当前最大的问题不是“按钮点不动”，而是 **数据侧的单点故障被放大成全站故障**（一台离线模拟器每分钟产生 1 条告警并自动建 1 张工单，47 分钟内从 124 条/99 张涨到 160 条/130 张），以及 **20 个并发重查询能把这套 SQLite 后端拖到 `/health` 都不可达**。

---

## 1. 测试副作用声明（必读）

1. **按任务要求创建了 3 个权限测试账号**（保留未删）：
   - `qa_viewer_2342 / viewer`
   - `qa_operator_2342 / operator`
   - `qa_auditor_2342 / auditor`
   - 初始密码 `QaPass2026!`，因平台强制首登改密，已改为 `QaPass2026!x`。
   - 建议验收结束后停用/删除这三个账号。相关审计见 `/oplog` 第 10–12 行（新建）与登录记录。
2. **误触发过一次写操作**：通用按钮遍历脚本把任务模板行的「复制」当成只读按钮点击，创建了 3 条副本（`id=7/8/9`，名称 `演练-172401 副本 ...`）。发现后**只删除了这 3 条自己产生的副本**，模板总数恢复为 6（`task_templates = [1,2,3,4,5,6]`）。除此之外没有删除任何数据。
3. 未修改 `admin` 密码，未修改任何既有账号的角色/状态。
4. 测试期间后端共被外部重启至少 4 次（非本会话执行）；并发测试后 `/health` 曾持续不可达 >90 秒，随后由外部恢复。重启时间点与证据见 §3。
5. 数据在测试期间持续增长：23:25 时 124 条告警 / 99 张工单，00:18 时 160 条告警 / 130 张工单。下文所有数字均标注采样时间，不要拿不同时间的数字直接对比。

---

## 2. 按钮逐页实测

证据目录：[docs/reviews/qa-evidence/](docs/reviews/qa-evidence/)。每页截图均为 1680×950，文件名与页面同名。图例：✅ 实测通过；⚠️ 部分可用/有前置条件；⛔ 按只读约束未点击（只验证了控件存在/禁用态）；❌ 实测失败。

### 2.1 实时监控

| 页面 | 按钮/控件（实测） | 点击后发生什么 | 判定 |
|---|---|---|---|
| **首页** `/dashboard` | 当前场站下拉、当前设备下拉、设备 chip ×3、锁定屏幕、告警铃铛 `137`、消息 `100`、可见光/热红外「打开全屏页」、云台控制、车体控制、点位行 | 场站/设备下拉展开；设备 chip 切换后卡片电量 `78%→—`、在线→离线、状态 `Free→UNKNOWN`，toast「已切换到 JCROB 模拟器」；锁定屏幕出现 🔒 遮罩；铃铛→`/alarms?status=unacked`；消息→`/messages`；全屏→`/video?source=1`；云台/车体仅 toast「写操作未开放」；点位→地图 | ✅（除云台/车体按设计不可用） |
| **机器人状态** `/robot-status` | 无业务按钮 | 纯状态卡 + 接口健康表 | ✅ |
| **地图监控** `/map` | 地图下拉、`导入`、平台地图卡片、`新增点位`、`退出打点`、缩放/拖拽 | `导入` 打开「导入地图」弹窗（PNG/JPG、名称、分辨率、原点），未上传；`新增点位` 禁用；`退出打点` 无变化；地图缩放/拖拽可用 | ⚠️ 导入只验证到弹窗 |
| **视频监控** `/video` | 视频源下拉、`测试连通`、`刷新列表`、`⚙ 摄像头配置`、`去管理视频源` | 视频源下拉展开；刷新重新拉 `/videos`；两个配置入口都跳 `/cameras`；页面 HLS/MSE 画面实际出图（截图可见监控画面） | ✅（测试连通未点，避免打外部摄像头） |
| **充电房监控** `/room` | 同视频页，按分组「充电房」过滤 | 同上；页面标题为「充电房监控」 | ✅ |
| **环境监测** `/env` | `去标定传感器` | 跳 `/env-device`；页面只有 1 台「可燃气体-泵房」= 7.6 %LEL，状态「注意」，时间「7 小时前」 | ✅（数据过期问题见 §6） |

### 2.2 巡检管理

| 页面 | 按钮/控件（实测） | 点击后发生什么 | 判定 |
|---|---|---|---|
| **任务管理** `/tasks` | 状态/循环筛选、`查询`、`重置`、`新建任务`、行 `☰/▶/■`、分页、`下发/暂停/继续/取消当前任务` | `查询` 重新 GET `/robots/1/tasks`；`重置` 恢复列表；`新建任务` 并不打开表单，而是 toast「下发/暂停/巡航在任务执行页」并跳 `/task-runs`；`☰` 打开任务详情弹窗；`▶/■` 也跳 `/task-runs`；`下发/暂停/继续/取消` 均跳 `/task-runs`，页面标注「写操作未开放」 | ⚠️ 按钮是“指引”不是执行 |
| **任务模板** `/task-templates` | `新建模板`、行 `下发/复制/✎/🗑` | `新建模板` 打开弹窗（名称/地图/循环/动作序列）；`复制` **立即 POST 创建副本**（本条是测试误触，已清理）；`✎` 打开编辑弹窗；`🗑` 弹出确认（未确认） | ⚠️ 读弹窗可用；复制是写操作 |
| **任务执行** `/task-runs` | `从模板生成计划`、状态筛选、`刷新`、行 `详情/巡航` | `从模板生成计划` 打开弹窗；`详情` GET `/task-runs/6` 后开弹窗；`刷新` 正常；`巡航` 未点（写） | ✅/⛔ |
| **巡检点位** `/points` | 地图下拉、点位名筛选、`查询`、`重置`、`去地图打点`、`同步到机器人` | 查询/重置刷新 6 条点位；`去地图打点` 跳 `/map?lib=1`；`同步到机器人` **disabled** | ✅ |
| **人工巡检** `/inspection` | `生成任务`、状态筛选、`刷新`、行 `详情/手机打卡/完成` | 刷新两张表（计划/任务）；`详情` 打任务详情弹窗；`手机打卡` 跳 `/m/task/2`；`生成任务/完成` 未点（写） | ✅/⛔ |
| **任务日历** `/task-calendar` | `返回上一页`、`回到驾驶舱` | 占位页，明确写「未接入」及缺什么数据源 | ⛔ 未点（与「未接入」一致） |

### 2.3 告警中心

| 页面 | 按钮/控件（实测） | 点击后发生什么 | 判定 |
|---|---|---|---|
| **告警记录** `/alarms` | 关键词、级别/状态下拉、`查询`、`重置`、`刷新`、`导出 CSV`、行 `✓/✎/→/⏹/⟲`、分页 | 查询/重置/刷新都重新拉 `/alarms`；`导出 CSV` 真实下载 `告警_2026-10-22.csv`，toast「已导出 10 条」（只导当前页）；`✎` 打开「处置告警」弹窗（处置说明必填）；`⏹` 打开「关闭告警」弹窗（结论下拉+备注）；`⟲` 跳录像回放并带日期/时刻；`✓/→` 未点（写） | ✅（写动作只到弹窗） |
| **工单** `/work-orders` | 状态下拉、`刷新`、行 `📱/派给/↑` | `刷新` 正常；`📱` 新标签打开 `/m/wo/{id}`；`派给` 展开人员下拉（未选择）；`↑` 未点（升级=写） | ⚠️ 派单未提交 |
| **AI 识别结果** `/ai-results` | 算法下拉、`刷新` | 刷新正常；当前仅 1 条「区域入侵 40% 未触发」 | ✅ |
| **告警规则** `/alarm-rules` | `去修改阈值`、`刷新告警状态` | 跳 `/settings`；刷新重新读阈值；页面显示电量 20%/10%、通信中断 10s，与 `/settings` 一致 | ✅ |

### 2.4 数据查询

| 页面 | 按钮/控件（实测） | 点击后发生什么 | 判定 |
|---|---|---|---|
| **任务数据** `/history/tasks` | `任务记录(2)`、`告警记录(N)`、`重置`、`刷新`、`导出 CSV` | Tab 切换、刷新正常；导出入口存在（未单独点） | ✅/⛔ |
| **告警数据** `/history/alarms` | Tab、起止日期、`重置`、`刷新`、`导出 CSV` | 同上；日期筛选存在 | ✅/⛔ |
| **巡检报表** `/reports` | `导出 Excel`、`打印 / PDF`、区间下拉、`统计` | `统计` GET `/reports/summary` 200，KPI 正常渲染；`打印 / PDF` 指向 `/reports/print` 新标签；**`导出 Excel` 后端 500**（§5） | ❌ 导出失败 |
| **运行数据** `/run-data` | 范围下拉、`刷新` | 刷新 GET `/telemetry`；10,527 采样点、电量 5–100%、里程 16,698.9m、离线 1.8% | ✅ |

### 2.5 设备管理 / 录像管理

| 页面 | 按钮/控件（实测） | 点击后发生什么 | 判定 |
|---|---|---|---|
| **设备台账** `/robots` | `刷新`、`新增设备`、行 `⇄/✎/🗑` | `新增设备` 弹窗（名称/类型/协议/场站/IP/端口/账号/密码）；`✎` 打开「编辑 · JCROB-01」；`⇄` 点击后**无可见变化、无 API 调用**（疑似死按钮）；`🗑` 未点 | ⚠️ |
| **摄像头** `/cameras` | 分组/名称筛选、`查询`、`重置`、`刷新`、`新增视频源`、行 `大屏显示/▶/✎/⚡/⇄/⏸/🗑` | 新增弹窗（含 go2rtc 流名下拉）；`✎` 打开编辑弹窗（密码显示 `***`，有「一键注册到 go2rtc」）；`⚡/⇄/⏸/🗑` 未点（测试/写） | ✅/⛔ |
| **环境传感器** `/env-device` | `刷新`、`新增传感器`、行 `＋/✎/🗑` | 新增/编辑弹窗字段完整（阈值留空=未标定）；当前 1 台已标定 5/10 | ✅/⛔ |
| **采集网关** `/sensor-gateways` | `新增网关`、行 `测试/🗑` | 新增弹窗（Modbus TCP/MQTT、寄存器、系数、周期）；当前 1 台「泵房气体报警器」运行状态 **异常** | ✅/⛔ |
| **录像计划** `/record/plan` | `开始录制`、`停止`、`去回放`、`新增计划` | `新增计划` 打开弹窗，但浏览器控制台报 3 次 `Failed to resolve component: DarkSelect`（组件未注册，摄像头下拉是坏的）；`开始录制/停止` 未点（写） | ❌ 弹窗有缺陷 |
| **录像回放** `/record/playback` | 摄像头下拉、日期、`查询`、`重置`、`去录像计划`、行 `▶/⤓/🗑` | `▶` 真实播放：请求 `/recordings/file...` 返回 **206 Partial Content**，toast「播放 1_20261022_154655.mp4」；列表 5 段与 `/recordings` 一致；`⤓` 元素匹配不到（可能不是 button），未验证下载；`🗑` 未点 | ✅ 播放 / ⛔ 下载 |

### 2.6 系统管理

| 页面 | 按钮/控件（实测） | 点击后发生什么 | 判定 |
|---|---|---|---|
| **消息中心** `/messages` | 类型下拉、`刷新`、`全部标为已读`、行 `查看` | `查看` 跳 `/alarms?status=unacked`；`刷新` 正常；`全部标为已读` 未点（写）；页面 248 条未读、248 行全量渲染 | ✅/⛔ |
| **用户管理** `/users` | `刷新`、`新建账号`、行 角色下拉/`⚿/⏸/🗑` | `新建账号` 弹窗（用户名/初始密码/角色）；`⚿` 是重置密码入口；`⏸/🗑` 未点；非 admin 直接访问只显示「只有管理员可以管理账号」 | ✅/⛔ |
| **系统设置** `/settings` | `撤销`、`保存配置`（无改动时禁用）、开关/数字项、`重新探测`、`刷新` | 表单可编辑；`重新探测` 触发 `/health/deep` 能力矩阵刷新；`保存配置` 未点（写）；写开关当前显示「关闭」，与 `/settings.robot.write_enabled=false` 一致 | ✅/⛔ |
| **告警通知** `/notify` | `新增通道`、行 `测试/⏸/✎/🗑`、`刷新` | 新增通道弹窗（企业微信机器人/Webhook/级别/静默期）；编辑弹窗可用；`测试` 未点（会真的发消息） | ✅/⛔ |
| **系统日志** `/oplog` | 动作下拉、`查询`、`重置`、分页 | 查询/重置/分页正常；共 277→300+ 条；页面没有“链自检”按钮 | ✅（无自检入口） |
| **接口密钥** `/keys` | `新建密钥`、行 `🗑` | 新建弹窗（名称+4 个 scope 复选框）；明文只显示一次；删除未点 | ✅/⛔ |
| **手机任务** `/m/task/1` | `扫码`、`正常`、`异常`、`跳过`、`完成本次巡检（2/2）` | 页面显示任务已完成 2/2，但「完成本次巡检」仍为可点击状态（只读未点，疑似可重复提交）；扫码会调摄像头 | ⚠️ 疑似 |
| **手机工单** `/m/wo/1` | `已完成` | 已完成工单，按钮 **disabled**；标题/等级/编号/期限/责任人 `#1` 与 `/work-orders/1` 完全一致；仍渲染「现场拍照（必拍）/核实结论（必填）」表单 | ✅（表单多余） |

---

## 3. 状态同步专项

### 3.1 同一数据的多处显示

采样时刻：2026-10-22 23:49–23:57，admin 会话。

| 数据 | 位置 A | 位置 B | 位置 C | 结果 |
|---|---|---|---|---|
| 机器人 1 电量/在线/状态 | 首页 `78% / 在线 / Free` | 机器人状态 `78% / 在线 / Free` | `/robots/1/status` `battery=78, online=true, status=Free` | ✅ 一致 |
| 告警总数/未确认/已确认 | 首页 donut `141 / 137 / 4`（等待 8 秒后） | `/alarms` `共 141 条`；`/alarms/stats` `141/137/4` | 报表 `告警总数 148`（近 7 天、另一时刻） | ✅ 同口径一致；注意报表是区间口径 |
| 工单数 | 工单页 `共 120 条`（23:57） | `/work-orders?limit=1` `total=119`（同一秒前后） | — | ✅ 实时增长导致 ±1 |
| 用户/点位/模板/录像/摄像头/传感器 | 用户页 7 行 | 点位页 6 行 | 模板 6 / 录像 5 / 摄像头 1 / 传感器 1 | ✅ 与 API 数量一致 |
| 环境读数 | 首页 7.6 %LEL | 环境监测 7.6「注意」 | 环境传感器 7.6；`/sensors` `latest=7.6, calibrated=true` | ✅ 值一致（但数据 7 小时前，见 §6） |
| 阈值 | 设置 `20 / 10 / 10s` | 告警规则 `20% / 10% / 10s` | `/settings.values` 同值 | ✅ 一致 |
| 写开关 | 设置「允许下发任务（写操作）= 关闭」 | `/settings.robot.write_enabled=false` | 任务页标签「写操作未开放」 | ✅ 一致 |

**首页首次进入的 0 值问题**：加载后约 2.4 秒截图时，首页告警 donut 显示 `0 / 未确认 0 / 已确认 0`，但 7 日柱状图已有 139 条；等 8 秒后变成 `141 / 137 / 4`。原因是 `robot.refreshAlarms()` 每 5 个轮询周期才拉一次告警，首屏先渲染空数组。不是两套数据打架，但首屏会误导（建议首屏显示骨架/“统计加载中”）。

### 3.2 切换设备后各处是否跟着变

操作路径（SPA 内导航，非整页刷新）：首页 → 点设备 chip「JCROB 模拟器」→ 实时监控 → 机器人状态 → 地图监控。

| 观察点 | 切换前（设备 1） | 切换后（设备 3） | 是否跟随 |
|---|---|---|---|
| 首页电量/在线/机器人状态 | 78% / 在线 / Free | —% / 离线 / UNKNOWN | ✅ |
| 顶栏状态 | 在线/正常 | **通信中断** | ✅ |
| 机器人状态页 | 78% / 在线 / Free / 位姿有值 | 离线 / 数据年龄 -1.0s / 所有卡片 `—` | ✅ |
| 机器人状态页「接口健康」 | 链路在线 是 / 数据年龄 0.6s / 连续失败 0 / 累计轮询 717 | **仍然显示 1 号机的健康数据**（在线、0.6s、0 失败） | ❌ 串台 |
| 首页「当前设备」下拉 | JCROB-01 | 显示 **「全部」**，不是 JCROB 模拟器 | ❌ |
| 地图监控 | map1 / 6 个点位 / 机器人轨迹 | 仍是 map1 / 6 个点位；没有提示“该设备无地图” | ❌ 串台 |
| 视频监控 | 充电房-可见光 | 仍是同一路视频源 | ⚠️ 视频是全局源，未按设备隔离 |
| 整页刷新后 | JCROB-01 | 回到 JCROB-01（Pinia 内存态，无 URL/localStorage 持久化） | ❌ 选择丢失 |

**根因证据**：
- 设备下拉的 options 被场站过滤：`deviceOptions = devices.filter(d => !site || d.station === site)`，当前场站是「默认场站」，而设备 3 属于「实验室」；从 chip 选中 3 后，`deviceId=3` 不在 options 里，DarkSelect 回退显示「全部」。[Dashboard.vue:112](web/src/pages/Dashboard.vue#L112)
- 地图页使用平台地图库的 `map1`，并未按 `robot.deviceId` 取图。[MapPage.vue](web/src/pages/MapPage.vue)
- 机器人状态的「接口健康」调 `/health/deep`（全局单例），不是 `/robots/{id}/status`。[RobotStatus.vue:49](web/src/pages/RobotStatus.vue#L49)
- 切换只在 Pinia 内存中生效，刷新即回默认值 1。[stores/robot.ts](web/src/stores/robot.ts)

**截图**：[robot_status_after_switch_spa.png](docs/reviews/qa-evidence/robot_status_after_switch_spa.png)（离线 + 接口健康仍“链路在线 是”）、[map_device3.png](docs/reviews/qa-evidence/map_device3.png)（3 号机仍显示 map1）。

### 3.3 告警处置后的首页 / 工单 / 审计同步

没有在本轮执行新的处置（只读约束），使用既有历史记录做闭环核对：告警 `#28`（2026-10-22 19:23:23 产生，19:41:44 确认，19:42:25 处置，19:42:27 关闭）。

- `/alarms?status=closed` 返回 3 条，其中 `#28`：`acked_by=admin`、`handled_by=admin`、`closed_by=admin`、`resolution=handled`。✅
- 操作日志有 3 条对应记录：
  ```
  19:42:27 admin alarm.close   alarm:28 handled {"resolution":"handled","note":"QA验收：已恢复，无需处理"}
  19:42:25 admin alarm.handle  alarm:28 QA验收：已现场确认，气体浓度恢复正常
  19:41:44 admin alarm.ack     alarm:28 机器人通信中断
  ```
- 消息中心有对应 3 条：`告警已确认`（#118）、`告警已处置`（#119）、`告警已关闭`（#120）。✅
- 首页统计把该告警计入「已确认 4」中的一条（已关闭 3 + 已确认 1）。✅
- **但没有生成/关联工单**：`/work-orders` 中不存在 `source_id=28` 的工单。也就是说“告警处置”和“工单闭环”是两条独立链路，处置告警不会自动建单/回填工单。如果验收口径要求“告警→工单闭环”，这里缺一环。⚠️

**注意**：`/alarms/{id}` 这个单条详情接口不存在（访问 `/api/v1/alarms/120` 返回 404），页面也没有告警详情路由；目前只能从列表/消息反查。

### 3.4 工单派单后手机页是否可见

- 现有工单中只有 2 张已派单（`#1`、`#4`），且都已关闭；**没有“派单后仍待处理”的工单**，因此没有做“派单 → 手机页立即出现”的端到端写入验证（只读约束）。
- 用 `#1` 做了静态一致性核对：
  - API：`title=泵体渗漏, level=critical, status=closed, assignee_id=1, due_at=2026-10-22T18:31, resolution=更换密封圈, mobile_url=/m/wo/1`
  - 手机页：`泵体渗漏 / 紧急 WO-20261022-001 · 已销号 / 泵房A 渗漏 / 期限 2026-10-22 18:31 责任人 #1 / 已完成(disabled)` → ✅ 标题、等级、编号、期限、责任人、状态全部一致。
- 结论：手机页渲染已派单工单没问题；“派单动作后立即可见”**未验证**（需要一次写操作）。

截图：[m_wo_1.png](docs/reviews/qa-evidence/m_wo_1.png)。

### 3.5 设置改了别处是否生效（写开关）

- `/settings.robot.write_enabled = false`；设置页显示「允许下发任务（写操作） 关闭」；任务页有「写操作未开放」标签。
- 后端在 `task_dispatch._require_write()` 里对下发/暂停/取消返回 `403 WRITE_LOCKED`（[task_dispatch.py](server/app/services/task_dispatch.py)）。
- **但预检接口不校验写开关**：`POST /api/v1/robots/1/commands/precheck` 返回 `200 {"ok":true,"reasons":[]}`，即使写开关是关的。用户会先看到“预检通过”，点下发才 403。建议把 `robot.write_enabled` 纳入预检 reasons。
- 未点击“保存配置”去改开关（写操作）；因此“改完立即生效、别处是否跟着变”只验证了当前关闭态的一致性，**未验证修改后的传播**。

### 3.6 环境数据 / 采集网关

- 1 台传感器「可燃气体-泵房」：7.6 %LEL，阈值 warn 5 / crit 10，`calibrated=true`，最后读数 `2026-10-22T17:05:33`。
- 采样时 23:57，环境页显示「7 小时前」；采集网关页显示「泵房气体报警器 运行 异常」；`/sensor-gateways/runtime` 也是异常。两处对“网关离线”的判断一致。✅
- 但环境页仍以绿色/黄色状态展示 7.6 并标「注意」，没有“数据已过期/不可信”的强提示；7 小时前的值用来判断当前超限，容易误导。建议超过 2×采集周期就置灰/标“过期”。

---

## 4. 并发与延迟

脚本：[scripts/qa_state_sync/load_probe.py](scripts/qa_state_sync/load_probe.py)（只发 GET，带 admin cookie）。原始结果：[load_probe.log](scripts/qa_state_sync/load_probe.log)、[load_probe.json](scripts/qa_state_sync/load_probe.json)。

### 4.1 20 并发 × 4 个接口

一次“正常”的采样（00:03 之前，后端健康）：

| 接口 | 成功/总数 | p50 | p95 | max | 平均响应体 |
|---|---|---|---|---|---|
| `/api/v1/robots/1/status` | 20/20 | 36.5 ms | 46.9 ms | 51.8 ms | 1.2 KB |
| `/api/v1/alarms` | 20/20 | 141.4 ms | 160.0 ms | 167.6 ms | 59 KB |
| `/api/v1/telemetry?hours=1` | 20/20 | 250.0 ms | 302.5 ms | 303.6 ms | 14 KB |
| `/api/v1/reports/summary` | 20/20（另一次采样） | 46 ms | 51 ms | 66 ms | 1.3 KB |

**但同一脚本在不同时间复现了整站卡死**：

| 时间 | 现象 |
|---|---|
| 00:02 第一次 | `telemetry` 20/20 全部 25s 超时；`reports/summary` 20/20 全部 25s 超时；随后的 100 次状态轮询前 2 次 25s 超时，第 3 次 20.7s；`/health` 开始返回 000 |
| 00:06 隔离复测 | 单独 20 并发 `telemetry?hours=1` 20/20 成功 p50 322ms；紧接着 20 并发 `reports/summary` 20/20 全部 30s 超时；再打 `telemetry?hours=24` 20/20 全部 30s 超时；`mix` 20+20 全部超时 |
| 00:07 | `curl -m 15 /health` = **000**，TCP 仍 LISTEN，进程 CPU 持续上升；>90 秒不可达，随后外部重启（PID 变化） |
| 00:04 | 另一次单独 20 并发 `reports/summary`：20/20 成功，p50 30–51ms |

**结论**：不是“某个接口稳定地慢”，而是 **20 个重查询并发 + 前序请求会非确定性地把整个进程拖死，连不查库的 `/health` 都不可达**。这比单个接口 500 更严重：现场 20 个浏览器同时打开报表/运行数据就可能触发。工作树里已经有人在加 `_SUMMARY_LOCK`/缓存/预热（未提交），但截至本报告未经过并发回归，不能算已修复。

### 4.2 连续 100 次轮询

健康状态下（00:12，前序负载已恢复）：

```
/robots/1/status × 100（间隔 200ms）
n=100  p50=17.2ms  p95=30.4ms  p99=31.8ms  max=35.3ms  codes={200:100}
>200ms 的尖刺：0
```

`/alarms × 100`（间隔 200ms）：

```
n=100  p50=27.3ms  p95=40.5ms  max=51.1ms  codes={200:100}
```

**5xx 数 = 0**。唯一一次“100 次里 2 次超时”的采样发生在 20 并发把后端拖死之后，不是常态轮询的问题；但这也说明“一个坏请求能把所有轮询一起拖下水”，需要熔断/隔离。

### 4.3 单请求基线

- `/reports/summary` 单请求：22–166 ms（冷/热差异）。
- `/reports/export.xlsx` 单请求：**500**（见 §5）。
- `/audit-logs/verify` 单请求：200 但 `ok=false`（见 §5）。

---

## 5. 权限（viewer / operator / auditor）

### 5.1 测试账号

按任务要求用 admin 创建（API，非 UI）：

```bash
POST /api/v1/users  {"username":"qa_viewer_2342","password":"QaPass2026!","role":"viewer"}
POST /api/v1/users  {"username":"qa_operator_2342","password":"QaPass2026!","role":"operator"}
POST /api/v1/users  {"username":"qa_auditor_2342","password":"QaPass2026!","role":"auditor"}
# 首登强制改密：POST /auth/password  old=QaPass2026! new=QaPass2026!x
```

返回均 `200`，`must_change_password=true`；改密后正常登录。原始结果：[permission_api.json](scripts/qa_state_sync/permission_api.json)。

### 5.2 接口矩阵（实测状态码）

| 接口 | viewer | operator | auditor | admin |
|---|---|---|---|---|
| `GET /auth/me` | 200 | 200 | 200 | 200 |
| `GET /robots`、`/robots/1/status` | 200 | 200 | 200 | 200 |
| `GET /alarms`、`/work-orders` | 200 | 200 | 200 | 200 |
| `GET /settings` | 200 | 200 | 200 | 200 |
| `GET /devices`、`/telemetry`、`/sensors`、`/notify/channels` | 200 | 200 | 200 | 200 |
| `GET /users` | **403** | **403** | **403** | 200 |
| `GET /audit-logs` | **403** | **403** | **200** | 200 |
| `GET /api-clients` | **403** | **403** | **403** | 200 |
| `POST /alarms/{id}/ack`（用不存在 id） | **403** | **404**（角色允许，实体不存在） | **403** | 未测 |
| `POST /devices/reload` | **403** | **403** | **403** | 未测 |
| `POST /users` | **403** | **403** | **403** | 200（建测试号实测） |
| `PUT /settings` | **403** | **403** | **403** | 未测（未提交，避免改配置） |
| `DELETE /api-clients/{id}` | **403** | **403** | **403** | 未测 |

403 返回体示例：`{"code":"FORBIDDEN","message":"需要角色 admin/operator"}`。
**后端权限矩阵基本正确**：auditor 只能看审计，viewer/operator 拿不到用户/密钥/审计；operator 可以确认告警（404 证明角色校验已过）。admin 的读接口均实测 200；写接口除 `POST /users`（建 3 个测试号）外均未提交，不写成“推断 200”。

### 5.3 菜单可见性（实测）

同一套菜单，三种角色：

| 菜单/页面 | viewer | operator | auditor |
|---|---|---|---|
| 用户管理 `/users` | **显示**（点进去是“只有管理员可以管理账号”） | **显示**（同左） | **显示**（同左） |
| 系统设置 `/settings` | **显示**（输入框可编辑；保存 disabled） | **显示**（输入框可编辑；改任一项后保存启用） | **显示**（输入框可编辑；保存 disabled） |
| 系统日志 `/oplog` | 菜单隐藏；直接访问显示 **空表“共 0 条”** | 菜单隐藏；直接访问空表 | 菜单显示；277 条正常 |
| 接口密钥 `/keys` | 菜单隐藏；直接访问文案 403 | 同左 | 同左 |
| 设备/告警/任务等 | 全部显示 | 全部显示 | 全部显示 |

**问题**：
1. `nav.ts` 只给 `oplog`、`api-keys` 配了 `roles`，`users`、`settings` 没配，所以 viewer/operator/auditor 都能看到入口（[nav.ts:84](web/src/config/nav.ts#L84)）。虽然后端 403，但“能点进去”本身违反三权分立的 UI 预期。
2. operator 的 `auth.canWrite = admin/safety/operator` 为 true；设置页输入框没有任何角色禁用，operator 改任一项后保存按钮即启用，但 `PUT /settings` 只允许 `admin/sysadmin/secadmin/safety` → **按钮能点，提交必 403**。另外 `Settings.vue:51` 定义了按 key 限制的 `canEditKey()`，但全文没有任何地方调用它，属于死代码（[Settings.vue:124](web/src/pages/Settings.vue#L124)）。
3. viewer/operator 直接访问 `/oplog` 时，页面捕获 403 后渲染成空表「共 0 条」，而不是“无权限”。这会让人误以为系统没有日志，而不是被拒绝。对比 `/keys` 会把「需要角色 admin/sysadmin」显示出来，两页错误处理不一致。
4. `users` 页本身的降级文案是好的（“只有管理员可以管理账号。当前账号角色：只读/操作员/审计管理员”）。

截图：[perm_viewer_menu.png](docs/reviews/qa-evidence/perm_viewer_menu.png)（系统管理下拉里仍有用户管理/系统设置）、[perm_viewer_users.png](docs/reviews/qa-evidence/perm_viewer_users.png)、[perm_operator_settings.png](docs/reviews/qa-evidence/perm_operator_settings.png)（表单可编辑+保存可用）、[perm_auditor_oplog.png](docs/reviews/qa-evidence/perm_auditor_oplog.png)。

---

## 6. 必须修 / 建议修 / 可忽略

### 6.1 必须修（P0/P1，带证据）

1. **告警/工单风暴（P0）**
   - 证据：00:18 `/alarms` 160 条（同源的 141 条采样中 137 条未确认，其余时刻相近）、`/work-orders` 130 条（绝大多数待派单，测试中仅见 2 张已关闭）；47 分钟新增 36 条告警、31 张工单，几乎全部来自同一台离线设备（robot_id=3）。截图 [work-orders.png](docs/reviews/qa-evidence/work-orders.png) 一屏 110 张「紧急 / 待派单」，标题重复「机器人通信中断（5 分钟内第 81/61/41/21 次）」。
   - 根因：`AlarmStore._check` 的 dedupe 窗口只有 60s；超出窗口后同指标继续新增；`work_orders.ensure_from_alarm()` 对**每一条严重告警**建一张工单（[work_orders.py:19](server/app/services/work_orders.py#L19)）。
   - 影响：工单队列不可用、消息中心 248 条、SQLite 持续写入、报表/首页被拖慢；值班员会直接忽略告警。
   - 修复方向：同 `(robot_id, metric)` 只保留一条“活动告警”，后续只更新 `last_seen/count/level`；告警恢复时自动 resolved；一张告警最多一张工单；对已有 130 张重复工单做一次性合并/关闭（需业务确认）。工作树已有 `_touch_open` 尝试（未提交、未验证）。

2. **报表导出 Excel 必 500（P0）**
   - 证据：
     ```bash
     curl -b cookies -o /tmp/x.xlsx -w "%{http_code} %{size_download}" \
       http://127.0.0.1:8000/api/v1/reports/export.xlsx
     # 500 21   （body: Internal Server Error）
     ```
     在进程内复现：
     ```
     TypeError: summary() got an unexpected keyword argument '_'
       at app/api/v1/reports.py:325 in export_xlsx
     ```
     `summary()` 的形参已改成 `user`，导出仍用 `summary(..., _=_)`。[reports.py:325](server/app/api/v1/reports.py#L325)
   - 影响：报表页「导出 Excel」按钮 100% 失败（`打印 / PDF` 是另一条路，未验证）。

3. **20 并发重查询可拖死整站（P0）**
   - 证据：§4；`/health` 返回 000 持续 >90s，需外部重启；一次 20 并发 `reports/summary` 全 25–30s 超时，另一次全 200（46ms）→ 非确定性。
   - 影响：20 个调度员同时打开报表/运行数据即可让全站 API（含状态轮询、登录）不可用。
   - 修复方向：除已有的缓存/单飞锁外，给重查询加独立线程池/超时/熔断；`/health` 绝不能依赖 DB/线程池；用 20/50 并发做回归门禁。

4. **审计链校验失败（P1，合规）**
   - 证据：
     ```bash
     curl -b cookies http://127.0.0.1:8000/api/v1/audit-logs/verify
     # {"ok":false,"broken_at":1,"reason":"row_hash 对不上（内容被改）","checked":1}
     ```
     复算 314 条带哈希记录：**id 1–128 全部 mismatch，id 129–314 全部 match**。说明第 129 条起换了哈希算法/规范化方式，旧链没有迁移。
   - 影响：`/oplog` 页面没有“自检”按钮，但一旦监管/验收调 `/audit-logs/verify` 就报“内容被改”，整个审计不可信。
   - 修复方向：把 1–128 标为 legacy（与无哈希老记录同策略），或按旧算法重算并锚定；上线前跑一次全链校验。

5. **切换设备后状态串台（P0，安全相关）**
   - 证据：§3.2；3 号机已显示“离线/通信中断”，但「接口健康」仍显示“链路在线 是 / 数据年龄 0.6s / 连续失败 0”；地图仍是 1 号机 map1；「当前设备」显示“全部”。截图 [robot_status_after_switch_spa.png](docs/reviews/qa-evidence/robot_status_after_switch_spa.png)。
   - 影响：操作员可能把 1 号机的健康状态当成 3 号机的，或在错误设备上下文里看地图/点位。
   - 修复：`/health/deep` 按设备返回或明确标注“平台级”；地图按 `robot.deviceId` 取图；设备下拉选项不要被场站过滤；设备选择写入 URL/query 或 localStorage。

6. **菜单把 14 个已交付页面标成「未接入」（P1，验收口径）**
   - 证据：菜单截图里「环境监测 / 任务模板 / 任务执行 / 人工巡检 / 运行数据 / 巡检报表 / 环境传感器 / 采集网关 / 录像计划 / 录像回放 / 告警通知 / AI 识别结果」都带「未接入」，`/oplog`、`/keys` 也同样；但本次实测这些页面全部有真实数据、真实接口（报表 141 条、运行数据 10527 点、模板 6 条……）。`nav.ts` 中只有 9 个条目写了 `real: true`，其余缺省 false（`task-calendar` 是唯一真正未接入的占位页）。[nav.ts:33](web/src/config/nav.ts#L33)
   - 影响：验收方会认为这些功能没做；与“已交付”事实冲突。
   - 修复：按实际状态补 `real: true`；只有「任务日历」保留未接入说明页。

7. **录像计划的 `DarkSelect` 未注册（P1）**
   - 证据：`/record/plan` 控制台 3 次 `[Vue warn]: Failed to resolve component: DarkSelect`；源码用了 `<DarkSelect>` 但没有 import（[RecordPlan.vue:235](web/src/pages/RecordPlan.vue#L235)）；「新增计划」弹窗的摄像头下拉因此是原生未知元素。
   - 影响：新增录制计划无法可靠选摄像头（无法真正完成计划创建）。

8. **权限 UI 与后端 403 不一致（P1）**
   - 证据：§5.3；operator 设置页「保存配置」可用但 `PUT /settings` 403；viewer/operator 能看到用户管理/系统设置菜单；viewer 直接访问 `/oplog` 显示“共 0 条”而非 403。
   - 影响：用户会反复点一个必然失败的按钮，或误以为无数据；三权分立的“不可见”没有做到。
   - 修复：菜单按角色隐藏 users/settings；operator 的 `canWrite` 与 settings 允许角色对齐（要么放开 operator，要么禁用保存）；oplog 403 显示明确无权限态。

9. **部署/升级缺列导致报表 500（P1，环境）**
   - 证据：23:35 首次 `GET /reports/summary` 返回 500；进程内 traceback：
     ```
     sqlite3.OperationalError: no such column: point_draft.arrive_radius_m
     ```
     23:41 后端被重启后，DB `point_draft` 出现 `arrive_radius_m` 列，接口恢复 200。说明已有库升级时没有跑迁移，靠重启 `create_all/补列` 才修好。
   - 影响：滚动升级/未重启的实例会持续 500；应在启动时做 schema 检查并在健康检查里暴露。

### 6.2 建议修（P2）

1. **预检不校验写开关**：`POST /robots/1/commands/precheck` 在 `robot.write_enabled=false` 时仍返回 `{"ok":true}`，点下发才 403。把写开关放进 `reasons`。
2. **消息角标 100 截断且无“99+”**：首页铃铛显示 137（告警），消息图标固定显示 100，而消息中心是 248 条未读；两个数字口径不同、无标签，容易被当成同步错误。[Dashboard.vue:359](web/src/pages/Dashboard.vue#L359)
3. **首页首屏 5 秒内告警统计为 0**：先渲染空 `robot.alarms`，donut 0/0/0，柱状图已有数据；应显示 loading 或首屏立即拉一次告警。
4. **环境读数过期无强提示**：7 小时前的 7.6 %LEL 仍以「注意」正常色展示；网关已「异常」。建议 >2×采集周期标“数据过期/不可信”并置灰。
5. **告警 CSV 只导当前页 10 条**：`exportCsv()` 用 `rows.value`（当前页），toast 也承认「已导出 10 条」。若用户期望“导出全部筛选结果”，会少数据；至少在按钮上写“导出本页”。
6. **回放列表出现已删除摄像头 `#2`**：录像 5 段中第 5 段显示 `#2`，但 `/videos` 只有 1 路；应显示“摄像头已删除”或隐藏。
7. **告警处置不产生/不回填工单**：`#28` 处置关闭后没有 `source_id=28` 的工单；告警与工单是两条独立链路。若方案承诺“告警→工单闭环”，需补自动建单或处置时选择关联工单。
8. **手机端已完成任务仍显示可提交**：`/m/task/1` 已 2/2 完成，但「完成本次巡检（2/2）」按钮仍可用（只读未点，疑似可重复 finish）。建议按任务状态禁用。
9. **操作日志无自检入口、无导出**：`/oplog` 只有查询/分页；`/audit-logs/verify` 只能手工调。建议页面上加“链自检”和导出，配合 §6.1-4 使用。
10. **设备台账 `⇄` 按钮无反应**：点击后无 UI 变化、无 API 调用（实测），疑似死按钮；要么实现“启用/停用/测试连接”，要么移除。

### 6.3 可忽略（P3）

1. 「任务日历」占位页：明确写了未接入原因，没有放假数据，符合当前阶段。
2. 视频/热红外“通道未接入”提示：真机/热像仪未接，文案诚实。
3. `打印 / PDF` 打开新标签：设计如此，未验证导出结果，不算缺陷。
4. 消息中心 248 行全量渲染、无分页：数据量再大才成问题，当前可用。
5. 首页两个“打开全屏页”都跳 `/video?source=1`（热红外未接时也跳同一路）：当前只有一路可见光，属可接受降级。

---

## 7. 未验证 / 测试限制

以下项目**没有执行写操作**，不能声称“能完成”，只能确认“入口/弹窗存在”：

- 新增/编辑设备、摄像头、传感器、采集网关、录像计划、通知通道、接口密钥、用户账号的**保存/创建**。
- 系统设置的保存、写开关切换、阈值修改。
- 告警的确认（✓）、转工单（→）、处置提交、关闭提交。
- 工单派单、升级、处置、复核、销号。
- 任务模板下发、复制后的业务效果；任务执行下发/暂停/继续/取消/巡航；人工巡检生成任务/完成；手机打卡的正常/异常/跳过/完成。
- 录像开始/停止；录像下载 `⤓`；打印/PDF 产物；地图导入上传；导出 Excel 修复后的结果。
- 工单“派单后手机页立即可见”的端到端写入链路（没有开放的已派单工单）。
- 通知通道“测试”实际投递（会发外部消息）。
- 修改设备选择后的整页刷新保持（当前实现无持久化，已按代码判断）。

另有两点环境限制：

- 测试期间后端被外部重启多次，个别时刻的 500/超时可能是重启窗口叠加；已在 §4 标注可复现与不可复现的采样。
- 工作树有未提交修改（reports 缓存/锁、alarms `_touch_open`、main 预热），本报告不能代表这些修改合并后的最终行为。

---

## 8. 复现命令与证据索引

### 8.1 关键复现命令

```bash
# 1) 登录
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}'
# 200 {"user":{"id":1,"username":"admin","role":"admin",...},"csrf_token":"..."}

# 2) 报表汇总（当前 200；23:35 曾 500 缺列）
curl -s -b cookies 'http://127.0.0.1:8000/api/v1/reports/summary?date_from=2026-10-16&date_to=2026-10-22'

# 3) 导出 Excel（500）
curl -s -b cookies -o /tmp/export.xlsx -w '%{http_code} %{size_download}\n' \
  'http://127.0.0.1:8000/api/v1/reports/export.xlsx'
# 500 21

# 4) 审计链自检（失败）
curl -s -b cookies http://127.0.0.1:8000/api/v1/audit-logs/verify
# {"ok":false,"broken_at":1,"reason":"row_hash 对不上（内容被改）","checked":1}

# 5) 告警/工单规模
curl -s -b cookies 'http://127.0.0.1:8000/api/v1/alarms?limit=1' | jq '.total'
curl -s -b cookies 'http://127.0.0.1:8000/api/v1/work-orders?limit=1' | jq '.total'

# 6) 并发/轮询
python scripts/qa_state_sync/load_probe.py
```

### 8.2 脚本与原始结果

| 文件 | 内容 |
|---|---|
| [recon.py](scripts/qa_state_sync/recon.py) | 34 个路由逐页截图 + 按钮/控制台/HTTP 错误采集 |
| [recon.json](scripts/qa_state_sync/recon.json) | 34 页快照（按钮、文本、console、HTTP 4xx/5xx） |
| [click_audit2.py](scripts/qa_state_sync/click_audit2.py) / [click_audit.json](scripts/qa_state_sync/click_audit.json) | 通用按钮点击（前 13 页；后续因误触写入被中止） |
| [click_targeted.py](scripts/qa_state_sync/click_targeted.py) / [click_targeted.json](scripts/qa_state_sync/click_targeted.json) | 定向只读点击（设备/摄像头/传感器/网关/录像计划/用户/告警弹窗） |
| [click_targeted2.py](scripts/qa_state_sync/click_targeted2.py) / [click_targeted2.json](scripts/qa_state_sync/click_targeted2.json) | 告警处置/关闭弹窗、报表统计、派给下拉、地图导入弹窗 |
| [load_probe.py](scripts/qa_state_sync/load_probe.py) / [load_probe.log](scripts/qa_state_sync/load_probe.log) | 20 并发 + 100 轮询 |
| [permission_api.json](scripts/qa_state_sync/permission_api.json) | viewer/operator/auditor 接口矩阵 |
| [accounts.json](scripts/qa_state_sync/accounts.json) | 三个 QA 账号 id |
| [docs/reviews/qa-evidence/](docs/reviews/qa-evidence/) | 55 张页面/弹窗截图 + 1 个导出 500 响应样本 |

### 8.3 重点截图

- [首页（8 秒后统计已对齐）](docs/reviews/qa-evidence/dash_loaded.png)
- [工单风暴：110 张紧急待派单](docs/reviews/qa-evidence/work-orders.png)
- [切换 3 号机后：离线，但接口健康仍显示 1 号机在线](docs/reviews/qa-evidence/robot_status_after_switch_spa.png)
- [切换 3 号机后：地图仍是 map1](docs/reviews/qa-evidence/map_device3.png)
- [viewer 菜单仍显示用户管理/系统设置](docs/reviews/qa-evidence/perm_viewer_menu.png)
- [operator 设置页：表单可编辑、保存可用（后端 403）](docs/reviews/qa-evidence/perm_operator_settings.png)
- [录像计划新增弹窗（DarkSelect 未注册）](docs/reviews/qa-evidence/modal_record_plan.png)
- [手机工单 #1：与 API 一致](docs/reviews/qa-evidence/m_wo_1.png)

---

## 9. 最终判定

- **按钮逐一点击**：只读按钮（查询/重置/刷新/详情/分页/导出 CSV/播放/弹窗打开）大部分能真实工作；写按钮按约束只验证到弹窗，未提交。真正“点了完不成”的明确项是 **报表导出 Excel（500）** 和 **录像计划新增弹窗（组件未注册）**；其余写按钮是“被设计锁定/需要授权”，不是坏。
- **状态同步**：机器人 1 的电量/在线/状态、告警数量、用户/点位/模板/录像数量、阈值在当前时刻一致；**切换设备后地图/接口健康/设备下拉三项串台**，是最高优先级的状态同步缺陷。
- **并发**：正常轮询 p50 17ms、100 次 0 个 5xx；但 20 并发重查询存在把全站（含 `/health`）拖死的非确定性故障，必须在上线前做并发回归。
- **权限**：后端 403 矩阵基本正确；前端菜单/按钮与后端允许角色不一致，operator 的“保存配置”是典型的必然 403 的按钮。

> 本报告只记录实际执行过的命令/截图/接口返回。未执行写操作的部分已统一列在 §7，未用“应该可以”替代实测。
