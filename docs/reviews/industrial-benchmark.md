# 工业级巡检平台对标清单（可落地版）

> 核对日期：2026-10-23
> 方法：联网读厂商产品页/官方文档/标准页 + 读本仓库代码（`server/app/models`、`api/v1`、`services`）。
> 口径：
> - **必须有（P0）**：缺了验收过不了，或出了事兜不住。
> - **应该有（P1）**：工业级标配，一期可裁剪，但必须写进二期与投标偏离表。
> - **加分（P2）**：投标差异化，不影响交付。
> - **不做（X）**：明确写进边界，避免被当成承诺。
> - 「我方现状」只描述**代码里能证明的**，不写“计划中”。
> 边界：**没有甲方合同、没有等保测评项、没有厂商内部资料**；厂商能力只取公开材料，标「公开页」；拿不到的部分标「不确定」。所有链接在 §9 汇总。

---

## 0. 一页纸结论

1. **工业级巡检平台的骨架是「资产台账 → 任务/工单 → 告警治理 → 证据闭环 → 报表考核」五段闭环，不是「地图 + 视频 + 机器人」三件套。** 我们现在的五段都有壳，缺的是每一段的**治理规则**：告警没有分级/搁置/泛滥抑制，工单没有 SLA/派工规则/复核，台账没有防爆与检定字段，报表没有行业口径。
2. **告警管理是验收最容易翻车的一项。** 工业现场不问“能不能报警”，问“一天报多少条、P1 有没有被淹没、能不能暂时屏蔽、屏蔽了谁负责”。ISA-18.2 的答案是：**分级（priority 1–4）、搁置（shelve，有时限有理由有审计）、泛滥抑制（死区/延时/抖动/首出/工况抑制）、KPI（≤6 条/小时/人，泛滥 <1% 时间）**。我们目前只有 `warn/critical` + 60s 去重 + 3 次升级，属于「有告警，没有告警治理」。
3. **任务与工单在工业里是两件事。** 任务=按计划去巡（到位率），工单=发现缺陷去消（消缺及时率）。南网口径把缺陷分**紧急/重大/一般**，分别「立即 / 一周内 / 半年内」处置；行业制度里危急缺陷普遍按 **24 小时** 卡。我们的 `work_order` 只有 `due_at` + 手工指派，没有等级→时限映射、没有派单规则、没有复核人。
4. **权限不只是三权分立。** 工业现场还有**两票三制**（工作票/操作票、交接班/巡回检查/定期试验轮换）、**双人复核**（操作人+监护人+许可人）、**LOTO 上锁挂牌**。平台侧对应的是：高危动作二次审批、交接班记录、操作票步骤留痕。我们现在 7 角色 + TOTP 够用，但这三样一个都没有。
5. **台账字段差一个数量级。** `robot` 表 21 个字段，是「一台联网设备」；工业台账是「一个有合规寿命的资产」：位号、层级、防爆标志/证书/有效期、区域等级、检定周期、责任人、备件、文档、生命周期状态。防爆场景验收**一定**会问 Ex 证书和区域等级。
6. **报表不是缺页面，是缺口径。** 现有 `/reports/summary` 已能给告警确认/处置时长、告警→工单时长、工单闭环率、按人巡检完成率、点位覆盖率、在线率——比很多商用平台的一期还全。缺的是**巡检到位率、缺陷率、消缺及时率、MTBF/MTTR、告警泛滥 KPI**，以及「口径写在哪、谁签字、能不能订阅」。
7. **最缺的 10 项按“验收会被追问”排序**见 §8：告警治理 → 闭环证据 → 防爆台账 → SLA/派工 → 行业报表口径 → 双人复核/交接班 → 事件录像 → 审计外锚 → 多场站隔离 → 可证明的可靠性。

---

## 1. 调研对象：它到底是什么，能抄什么

> 关键判断先说：**这些对象不在同一层。** 海康 8700 是「综合安防集成平台」，申昊/亿嘉和/国自是「机器人本体 + 行业集控」，西门子/施耐德是「DCS/SCADA」，ThingsBoard/HA 是「IoT 平台/智能家居」，Open-RMF/VDA5050 是「车队调度标准」，FUXA/OpenSCADA 是「组态」，Grafana/Node-RED 是「看板/编排」，ISA 三套是「规范」。**对标要按层对，不能拿 8700 的“巡查”当设备巡检。**

### 1.1 商用

| 对象 | 它实际是什么 | 可抄的（具体到模块/字段） | 不要抄的 | 链接 |
|---|---|---|---|---|
| 海康 iVMS-8700 | 智能建筑**综合安防集成平台**，SOA，九大子系统：视频、报警、门禁、访客、梯控、**巡查**、考勤、消费、停车场；支持多级联网、电子地图、消防联动、网管 | ①「一个平台管多子系统」的**模块化授权**思路；② 电子地图 + 点位 + 视频 + 报警**四联动**；③ 巡查（巡更）的**路线-打点-漏检**模型；④ 设备网管（在线/离线/故障） | 它的「巡查」是**保安巡更**（人到点打卡），不是设备状态巡检；不要把巡更路线当巡检任务卖 | [a&s 产品库](https://product.asmag.com.cn/46085.html) |
| 申昊科技 L4-G2 | 油气化工**防爆轮式巡检机器人**：Ex d IIC T6 Gb / Ex tb IIIC T80℃ Db 双认证，可进 Zone 1/2 + 21/22；激光+IMU+里程计 ±10mm；4 种气体（20+ 可选）+ 32 倍可见光 + 红外 384×288 ±2℃；全面/定制/手动/夜间/**脱机** 五种模式；无线自动充电 | ① **防爆台账字段**（Ex 标志、温度组别、区域等级、证书）；② 检测项清单（气体/红外/可见光/声学）→ 平台的「检测项-算法-阈值」模型；③ **脱机巡检**（断网也能跑完，回来补传）；④ 一次巡检完成多维检测的**任务编排** | 不要把「机器人参数」当「平台能力」；它的平台侧细节公开页没有 | [L4-G2 产品页](https://www.shenhaoinfo.com/l4-g2-shir-4000ex-%e9%98%b2%e7%88%86%e8%bd%ae%e5%bc%8f%e5%b7%a1%e6%a3%80%e6%9c%ba%e5%99%a8%e4%ba%ba/) |
| 亿嘉和 | 电力/轨交/清洁机器人本体厂：SI300 简易巡检、D200 操作机器人、Z200 带电作业、TR100 轨交车辆巡检、N100 充电系统 | ① **操作机器人**的产品形态（巡检之后要能操作，平台要下发力控/按钮动作）；② 电力行业「集控站」话术与指标 | 官网以本体为主，**平台模块公开信息很少**，投标要技术协议 | [SI300](https://www.yijiahe.com/robot-si300) |
| 国自机器人 InView | 新一代智能巡视平台：机器人+摄像头+无人机+在线传感**多源协同**；自动/半自动/紧急三种任务模式；自动生成告警记录、巡检报告、运维建议；数字孪生；信创/等保三级；一站式 APP | ① **多源设备统一编排**（不是只有机器人）；② 任务三模式（自动/半自动/紧急）；③ 「告警记录 + 巡检报告 + 运维建议」三件套的输出物；④ 信创与等保三级作为**交付门槛**写进方案 | 数字孪生是演示层，别当一期范围 | [InView 软件页](https://www.gzrobot.com/intelligentInspection/software) |
| 西门子 SIMATIC PCS 7 | 过程工业 **DCS**，含 Maintenance Station 做**资产/维护管理**（设备台账、维护计划、备件），OS 侧做报警归档/操作记录 | ① **资产-维护-工单**一体的数据模型（Maintenance Station 的思路）；② 报警归档与操作日志的**长期可追溯**；③ 「控制器/现场设备/仪表」分层台账 | 它是 L2 控制系统，不是巡检平台；不要声称「兼容 PCS 7」除非真做 OPC UA/A&E | [PCS 7 产品页](https://www.siemens.com/en-us/products/process-control/simatic-pcs-7/) |
| 施耐德 EcoStruxure PME / Power Operation | 电力监控与 **SCADA**：PME 提供 **30+ 预置报表**，可手动/定时/**事件触发**，输出 PDF/HTML/CSV；仪表盘可配置、可嵌入外部页面、Kiosk 视图；Power Operation 做实时单线图/报警/波形；支持 OPC UA/SNMP | ① **报表订阅 + 事件触发导出**（不是只有“点一下生成”）；② 报表格式三件套 PDF/HTML/CSV；③ 报警 + 波形 + 事件顺序（SOE）联合分析；④ 对外接口 OPC UA/SNMP 的定位 | 强电专业报表（电能质量/谐波）与我们无关，只抄**形态**不抄内容 | [PME 报表与看板](https://product-help.se.com/docs/EcoStruxure/Power-Operation-2022/content/2_planning/pme/advrprtnganddash.htm) |

### 1.2 开源

| 对象 | 它解决什么 | 可抄的 | 不要抄的 | 链接 |
|---|---|---|---|---|
| ThingsBoard | 设备/资产模型、设备 profile（传输方式+编解码+告警规则）、资产关系、遥测、规则链、告警生命周期、仪表盘、RPC | ① **device profile**：把「接入参数/编解码/阈值」从代码挪到配置；② **asset relation**：厂区→设备→点位；③ **告警生命周期**（ACTIVE_ACK/ACTIVE_UNACK/CLEARED_ACK/CLEARED_UNACK）；④ 规则链的「节点化」表达 | 微服务 + Kafka + 多租户，单机 4 周 MVP 扛不住 | [device profiles](https://thingsboard.io/docs/user-guide/device-profiles/) · [assets](https://thingsboard.io/docs/user-guide/assets/) · [alarms](https://thingsboard.io/docs/user-guide/alarms/) · [rule engine](https://thingsboard.io/docs/user-guide/rule-engine-2-0/overview/) |
| Home Assistant | 设备-实体-区域的组织模型：Area（区域）、Floor（楼层）、Label（标签，可多对多）、Category；实体可继承设备区域，也可单独覆盖 | ① **Area/Floor** 层级（我们是 `station` 字符串，差这一层）；② **Label 多对多**（同一设备可同时属“防爆区”“A 班”“关键设备”）；③ 实体继承 + 覆盖的规则 | 家居场景的自动化 DSL、云依赖 | [Grouping your assets](https://www.home-assistant.io/docs/organizing/) |
| Open-RMF | 多机器人**任务队列 + 无冲突资源调度 + 车队适配器**（门/电梯/充电桩等资源协调） | ① task queuing / 优先级 / 抢占；② **资源锁**（同一段路/电梯/充电桩互斥）；③ fleet adapter 的接口分层 | ROS 2 运行时；单机 1–2 台用不上 | [OpenRMF docs](https://openrmf.readthedocs.io/en/latest/) |
| VDA5050 v3.0.0 | AGV/AMR 与车队系统的 MQTT 接口：Order（node-edge 图，`orderId`+`orderUpdateId`，released/base 与 horizon）、InstantActions、State（≥30s 或事件触发）、Factsheet、Connection（LWT + retained）、Zones、Errors | ① **订单幂等三元组**（orderId/orderUpdateId/actionId）；② **base/horizon** 的「已释放/未释放」语义；③ **连接契约**（LWT + retained + heartbeat）；④ **错误数组**（code/description/level）替代字符串 | 不要声称合规；我们只借消息模型 | [VDA5050_EN.md](https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md) |
| FUXA / OpenSCADA | Web 组态/HMI：tag 定义、驱动、画面、历史、报警 | ① **tag 元数据**（工程单位/量程/死区/采集周期/归档）；② 画面/面板复用（faceplate）；③ 报警分级与颜色规范 | 整套组态壳；驱动体系与我们不匹配 | [FUXA](https://github.com/frangoteam/FUXA) · [OpenSCADA](https://oscada.org/) |
| Grafana | 看板 + 告警 + 多数据源 | ① 面板即配置（JSON 化）；② 告警规则与静默；③ 变量/下钻 | 不要把它当业务系统；只做运维面 | [Grafana docs](https://grafana.com/docs/grafana/latest/) |
| Node-RED | 低代码流程编排（HTTP/MQTT/DB/邮件节点） | ① 非安全类胶水（告警转发 MES、报表推送）可视化编排；② 流程即配置的思路 | 安全链路（急停/下发/联锁）绝不能放进去 | [Node-RED docs](https://nodered.org/docs/) |

### 1.3 规范

| 规范 | 它管什么 | 对我们最硬的三条要求 | 链接 |
|---|---|---|---|
| ISA-18.2（+TR18.2.1/2/3/5/8） | 报警全生命周期：报警哲学、辨识与合理化、基础设计、实施、运行、维护、**监控与审计** | ① 必须有**成文的报警哲学**（分级依据、响应时间、搁置规则）；② 必须支持 **shelving**（有时限、有理由、有审计）与**泛滥抑制**（TR18.2.3 明确把 dynamic alarming / alarm shelving 列为基础设计手段）；③ 必须持续监控 **报警率、standing alarms、泛滥、操作员响应**（TR18.2.5） | [ISA-18 系列](https://www.isa.org/standards-and-publications/isa-standards/isa-18-series-of-standards) · [18.2](https://www.isa.org/products/ansi-isa-18-2-2016-management-of-alarm-systems-for) · [TR18.2.3](https://www.isa.org/products/isa-tr18-2-3-2015-basic-alarm-design) · [TR18.2.5](https://www.isa.org/products/isa-tr18-2-5-2022-alarm-system-monitoring-assessme) |
| IEC 62443 | 工业自动化与控制系统的网络安全：**分区（zone）/管道（conduit）**、安全等级 SL1–4、4-1 产品开发安全、4-2 组件技术要求、3-3 系统要求、2-1 资产所有者安全计划 | ① 网络**分区**：机器人/相机/办公网/平台分区，跨区只走管道；② 组件级要求：账号、审计、会话、完整性；③ 供应链/补丁管理（2-3） | [ISA/IEC 62443 系列](https://www.isa.org/standards-and-publications/isa-standards/isa-iec-62443-series-of-standards) |
| ISA-95（IEC 62264） | 企业与控制的集成分层：**L0 物理过程 / L1 传感与操纵 / L2 监控与监督控制 / L3 制造运行管理 / L4 业务计划与物流**；设备层级 Enterprise→Site→Area→WorkCenter→WorkUnit | ① 我们是 **L3**，不是 L1/L2，不承担控制与安全回路；② 台账必须按 **Site/Area/WorkUnit** 分层，否则报表无法按区域聚合；③ 与 L4（ERP/EAM）的接口边界要写清 | [ISA-95](https://www.isa.org/standards-and-publications/isa-standards/isa-95-standard) |

---

## 2. 标准功能模块（按层，标注必须有/加分）

### 2.1 分层总览

| 层 | 工业级叫什么 | 典型系统 | 我们对应物 | 结论 |
|---|---|---|---|---|
| L4 业务 | ERP/EAM/资产与工单主数据 | SAP PM、Maximo | 无 | 合同外，留接口 |
| **L3 作业** | 巡检/运维/EHS 管理 | 国自 InView、申昊集控、我们的平台 | **本平台** | 主战场，缺治理规则 |
| L2 监控 | SCADA/HMI/报警呈现 | PCS 7、PME、FUXA | Vue 驾驶舱 + 自绘地图 | 有壳，无 tag/历史/报警治理 |
| L1 控制 | 导航/本体控制 | JCROB、Nav2 | 厂商本体 | 不做，正确 |
| L0 现场 | 仪表/传感器/门禁/PLC | 气体报警器、温湿度、PLC | Modbus TCP / MQTT | 最薄 |
| 横向 | 安全/审计/可观测/数据治理 | — | 零散实现 | 需补齐 |

### 2.2 模块清单（P0 必须有 / P1 应该有 / P2 加分 / X 不做）

| # | 层 | 模块 | 工业级包含什么（可验证的点，不是形容词） | 级别 | 我方现状（代码证据） |
|---|---|---|---|---|---|
| 1 | L0 | 机器人接入 | 多厂商适配器、能力探测、断线重连、指令幂等、脱机巡检补传 | P0 | 有：`adapters/registry.py`、jcrob/deeprobotics 两家；无脱机补传 |
| 2 | L0 | 固定设备接入 | Modbus RTU/TCP（批量读、字节序）、OPC UA、MQTT QoS1/LWT、4–20mA/IO | P0（Modbus/MQTT）/P1（OPC UA） | 弱：50 行 Modbus 03/04，一寄存器一连接；MQTT QoS0 |
| 3 | L0 | 视频接入 | RTSP/ONVIF 发现、GB28181 信令与级联、多路、硬件转码、流健康 | P1（国标场景 P0） | 弱：go2rtc + 2 路 ffmpeg，手工 RTSP |
| 4 | L1 | 设备影子/状态同步 | desired/reported、版本号、字段级时间戳、部分过期可见 | P0 | 弱：进程内 `StateCache`，重启即失忆 |
| 5 | L1 | 协议与数据契约 | 内部 canonical 模型（id/type/capability/unit/ts/error_code）、版本化 | P1 | 弱：三套语义各写各的 |
| 6 | L2 | 实时监视 | 组态画面/单线图、实时值+质量码、趋势、多画面 | P1 | 弱：Vue 页面 + Canvas 地图，无质量码 |
| 7 | L2 | 地图与点位 | 多图层、点位分组、坐标标定与残差校验、禁行区/电子围栏 | P0 | 有：`MapPage/Points`、两点标定；无围栏 |
| 8 | L2 | 视频联动 | 告警/点位/地图/视频四联动，预置位，事件片段 | P0 | 弱：`camera_id` 固化到告警，无预置位/片段 |
| 9 | L2 | 报警呈现 | 报警条/列表/声音分级、首出高亮、按区域/设备过滤、泛滥折叠 | P0 | 弱：列表 + 级别，无首出/折叠 |
| 10 | L3 | **告警治理** | 分级(P1–P4)、搁置、泛滥抑制、KPI、合理化记录 | **P0** | **无**：只有 warn/critical + 60s 去重 |
| 11 | L3 | 巡检计划 | 班次/路线/检查项/责任人/周期、计划与任务分离 | P0 | 有：`InspectionPlan/Task`、shift |
| 12 | L3 | 机器人任务 | 模板、下发、暂停/继续/取消、进度、到达判定、失败重派 | P0 | 有：`task_dispatch/cruise`；无队列/优先级/重派 |
| 13 | L3 | 人工巡检 | 扫码打点、拍照、异常上报、离线可用、防代打卡 | P1 | 有：`MobileCheck`；离线不确定 |
| 14 | L3 | 工单 | 来源（告警/巡检/AI/人工）、等级、SLA、派单规则、转派、挂起、复核、销号 | **P0** | 弱：`work_order` 有 due_at/升级；无 SLA 映射/派单规则/复核人 |
| 15 | L3 | 缺陷管理 | 缺陷定级（紧急/重大/一般）、消缺时限、重复缺陷、缺陷库 | P0 | 无：只有工单，无缺陷实体 |
| 16 | L3 | 两票 | 工作票（一/二种）、操作票（步骤/监护人/许可人/终结）、动火/受限空间 | P1（电力/石化 P0） | 无 |
| 17 | L3 | 交接班 | 班次、交接事项、未闭环告警/工单移交、双方签名、时间戳 | P1（连续运行场景 P0） | 无（只有 `shift` 字段） |
| 18 | L3 | 双人复核 | 高危动作二次审批、操作人≠复核人、审批留痕 | P1 | 无 |
| 19 | L4 | 资产台账 | 位号、层级、防爆/检定/维保、文档、生命周期、责任人 | **P0** | 弱：`robot` 21 字段，无合规字段 |
| 20 | L4 | 报表 | 巡检率/缺陷率/消缺及时率/在线率/告警 KPI/资产到期；订阅+导出 | P0 | 弱：`/reports/summary` 有 20+ 指标，无行业口径/订阅/签章 |
| 21 | L4 | 考核 | 按人/班组：任务完成、异常数、工单闭环、超期 | P1 | 有：`inspection_performance` |
| 22 | 横向 | 权限 | RBAC + 对象级（场站/区域/设备）+ 数据范围 + 临时授权 | P0 | 有 7 角色；无对象级/数据范围 |
| 23 | 横向 | 审计 | 全写操作、字段级 diff、不可篡改（哈希链+外锚）、导出留痕 | P0 | 有哈希链（同库）；无外锚/字段级 diff |
| 24 | 横向 | 身份 | 本地账号+口令策略+MFA；SSO/OIDC/LDAP；服务间 mTLS | P0（本地）/P1（SSO） | 有 TOTP/锁定/密码历史；无 SSO |
| 25 | 横向 | 通知 | 分级路由、值班表、重试、去重、回执、升级 | P0 | 有：`notify` 多渠道+重试+HMAC |
| 26 | 横向 | 可观测 | /metrics、日志集中、trace、平台自身告警、SLO | P1 | 弱：`/metrics` + `/health/deep`，无 Prometheus 栈/日志聚合 |
| 27 | 横向 | 备份灾备 | 3-2-1、加密、异地、定期恢复演练、RPO/RTO 写进合同 | P0 | 弱：本地 mysqldump 14 天，无异地/演练 |
| 28 | 横向 | 数据保留 | 原始/聚合分级、分区、归档、法务留存 | P1 | 弱：单表 DELETE，无分区/聚合 |
| 29 | 横向 | 规则引擎 | 条件/时序/窗口可配置，不改代码 | P1 | 无：阈值在 Python 里 |
| 30 | 横向 | 集成接口 | OpenAPI 版本化、幂等键、Webhook、OPC UA/GB28181 对外 | P1 | 弱：有 OpenAPI，无版本化/幂等键 |
| 31 | 横向 | 移动端 | 巡检/工单/告警/审批/扫码，离线缓存 | P1 | 有：`MobileCheck/MobileWorkOrder` |
| 32 | 横向 | 数字孪生/3D | 设备模型 + 实时映射 + 空间定位 | P2 | 无（不建议一期） |
| 33 | 横向 | 信创/等保 | 麒麟/统信、达梦/人大金仓、等保三级测评项 | P2（政企 P1） | 无 |
| 34 | X | 功能安全 | 安全 PLC、急停回路、SIL 认证 | X | 明确不做，不宣传“平台急停” |
| 35 | X | 自研 SLAM/导航 | 定位、规划、避障 | X | 厂商负责 |

> **模块层面的差距不是数量，是“治理深度”。** 35 项里我们有 12 项「有/弱」，但 P0 里真正缺的是 #10、#14、#15、#19、#22、#23、#27——全是“出了事要被追责”的项。

---

## 3. 告警管理：ISA-18.2 怎么做到“专业”

### 3.1 先分清四个词（很多方案在这里就错了）

| 词 | 含义 | 我们的实现 | 问题 |
|---|---|---|---|
| 报警（alarm） | 需要**操作员动作**的异常 | `alarm_record` | 边界未定义：传感器超限、平台自检、AI 结果都往同一张表写 |
| 事件（event） | 只记录、不需要动作 | 混在 `alarm_record` / `operation_log` | 没有区分，导致报警数虚高 |
| 提示（notification） | 给非操作员（维修/管理）的信息 | `messages` / `notify` | ISA-TR18.2.8 专门讲这个，我们没有分层 |
| 缺陷（defect） | 设备已存在的劣化，需**工单**处置 | `work_order`（source=alarm/manual/ai） | 没有独立缺陷实体与定级 |

**专业做法**：报警只给“必须马上做动作”的；其余走 notification/event。否则 KPI 永远不达标——因为分母里塞满了不需要动作的东西。

### 3.2 分级：`level` 不是 `priority`

- 我们现在的 `level`（warn/critical）是**严重度**；ISA-18.2 要的是 **priority（优先级）**，由「后果严重度 × 允许响应时间」共同决定，通常 4 级（P1–P4），并有**目标分布**：约 80% 低优先级、15% 中、5% 高。
- 只有严重度、没有优先级，结果是：所有 critical 一起响，操作员无法排序；而“严重但不紧急”的会把“不严重但 1 分钟内必须处理”的挤掉。

**建议的分级矩阵（写进报警哲学，作为配置依据）**：

| 后果 \ 允许响应 | ≤1 min | ≤5 min | ≤30 min | >30 min |
|---|---|---|---|---|
| 人身/火灾/爆炸/环保超标 | **P1** | P1 | P2 | P2 |
| 主机停运/整线停机/机器人失控 | P1 | **P1** | P2 | P3 |
| 设备劣化/单点超限/电量低 | P2 | **P2** | P3 | P4 |
| 提示/统计类 | P3 | P3 | **P4** | P4 |

**每个 priority 必须绑定**：颜色、声音、是否弹窗、通知对象、确认时限、升级路径、能否搁置。这七项是配置，不是代码。

| 优先级 | 典型场景 | 颜色/声音 | 确认时限 | 通知 | 可搁置 | 升级 |
|---|---|---|---|---|---|---|
| P1 | 可燃气超限、急停、碰撞、火警、机器人失联>30s | 红/连续声 | 1 min | 值班+班长+安全员+短信 | **否**（需班长特批，≤30min） | 1min 未确认→班长，3min→厂长 |
| P2 | 高温、超压、低电、任务失败、视频中断 | 橙/间歇声 | 5 min | 值班+班长 | 是（≤4h，需理由） | 15min 未确认→班长 |
| P3 | 单点波动、通信重连、门禁异常 | 黄/单声 | 30 min | 值班 | 是（≤8h） | 2h→班长 |
| P4 | 统计/提示/自恢复 | 蓝/无声 | 当班 | 列表 | 是（≤24h） | 不升级 |

### 3.3 搁置（shelve）：不是“屏蔽”，是“有时限的、有责任的静音”

工业现场一定会有人问：“这个测点在检修，能不能先别报？”——正确回答是 **shelve**，不是 disable。三者的区别必须写进产品：

| 手段 | 时限 | 谁批准 | 是否仍记录 | 是否计数 | 到期行为 | 适用 |
|---|---|---|---|---|---|---|
| **Shelve（搁置）** | 15min/30min/1h/4h/8h/自定义（操作员≤8h，工程师≤30d 需审批） | 操作员（填理由） | 是 | **否**（不计入报警数、不发声） | **自动恢复**并重新要求确认 | 检修、调试、已知异常 |
| Suppress by design（设计抑制） | 长期 | 工程师+变更单 | 是 | 否 | 随配置生效 | 工况联锁、因果派生 |
| Disable（禁用） | 无限期 | 管理员+审批 | 是 | 否 | 不自动恢复 | 极少数，需变更管理 |

**字段设计（可直接加到 `alarm_record` 或独立 `alarm_shelve` 表）**：

| 字段 | 类型 | 说明 | 必填 |
|---|---|---|---|
| `shelved` | bool | 当前是否搁置 | 是 |
| `shelved_by` | str | 操作人 | 是 |
| `shelved_at` | datetime | 开始时间 | 是 |
| `shelve_until` | datetime | 到期时间（服务端算，不信客户端） | 是 |
| `shelve_reason` | str(200) | **必填**，下拉+自由文本（检修/调试/已知故障/备件等待） | 是 |
| `shelve_scope` | enum | point / device / group | 是 |
| `shelve_approved_by` | str | >8h 或 P1 时的审批人 | 条件 |
| `unshelved_at/by/reason` | — | 提前解除留痕 | 否 |
| `auto_unshelved` | bool | 到期自动恢复标记 | 是 |

**交互与审计要求（验收会逐条点）**：
1. 搁置必须弹窗填**理由**，不能一键静音；
2. 搁置中的报警在列表里显示 `[已搁置 剩余 02:13]`，可一键解除；
3. 有一个「搁置清单」页：谁、为什么、什么时候到期、影响的点位；
4. 搁置**不删除**任何记录，事件仍进历史；
5. 到期**自动恢复**，若条件仍存在则重新进入待确认（不是“恢复即关闭”）；
6. P1 默认不可搁置，需班长角色审批且 ≤30min；
7. 所有搁置/解除/到期都进审计（含理由）；
8. 重启不丢（落库，不存内存）。

> 业界实现可直接参照 [QtALH 的定时搁置](https://ops.aps.anl.gov/manuals/QtALH/operate/shelving.html)：预设 15m/30m/1h/4h/8h + 自定义，用户名与理由必填，搁置项不计入报警数/不发声，列表可查倒计时，到期自动回归，变更留痕。这套交互比多数商用 HMI 还完整，值得照抄交互、不抄代码。

### 3.4 泛滥抑制（alarm flood）：8 个手段，按性价比排序

| # | 手段 | 怎么做 | 解决什么 | 我们的现状 |
|---|---|---|---|---|
| 1 | **死区/回差** | 报警置位阈值与复位阈值差 1–5% 量程（如高温 80℃ 报、78℃ 复位） | 临界点反复触发 | 无（`sensor.warn_high` 单阈值） |
| 2 | **延时确认（on-delay）** | 连续 N 秒/ N 个采样满足才报；复位同理 | 瞬时毛刺 | 无 |
| 3 | **抖动识别（chattering）** | 1 分钟内 ≥3 次置位/复位 → 标记“抖动”，自动降级并提示整定 | 最吵的那批点 | 无（只有 60s 去重） |
| 4 | **首出（first-out）+ 因果抑制** | 一组关联报警只报第一个，派生项折叠为“由 X 引起” | 一个根因报 30 条 | 无 |
| 5 | **工况/状态抑制** | 设备处于“检修/停机/调试/离线”时不报或降级 | 检修期间刷屏 | 无（有 `is_active` 但不用） |
| 6 | **分组汇总** | 同设备/同区域 >N 条折叠成一条“设备 X 有 12 条报警” | 视觉淹没 | 无 |
| 7 | **洪泛期分级过滤** | 洪泛期间只显示 P1/P2，其余计数折叠 | 关键报警被淹没 | 无 |
| 8 | **动态阈值** | 按工况/负载/季节调整阈值 | 正常工况误报 | 无 |

**洪泛的行业定义（写进文档，避免各说各话）**：同一操作员 **10 分钟内收到 ≥10 条报警**为洪泛开始，**10 分钟内 <5 条**为结束（起始条件取 Honeywell 报警管理白皮书的定义，结束条件为业界常用配套口径，见 [Honeywell Alarm Management](https://process.honeywell.com/content/dam/forge/en/documents/gated/honeywell-alarm-management-standards-whitepaper.pdf)）。ISA-18.2 对应的目标是**洪泛时间占比 <1%**。

**注意 KPI 的口径陷阱**：报警率不能简单用“日总量/24h”算，也不能从“1 条/10 分钟”外推到 144 条/天——见 [ProcessVue 对报警 KPI 的批评](https://www.processvue.com/downloads/Alarm_system_performance_KPIs_V1_0.pdf)。正确做法是**按班次/按小时统计中位数与 P95**，并单列洪泛时段。

### 3.5 KPI 表（可直接做成“报警治理”看板）

| KPI | 公式 | 行业目标 | 数据来源 | 我们现在能不能算 |
|---|---|---|---|---|
| 平均报警率 | 报警数 ÷ 运行小时 ÷ 操作员数 | **≤6 条/h/人**（≈150 条/24h） | `alarm_record.started_at` | 能（需去重口径） |
| 峰值报警率 | 任 10 分钟窗口最大值 | **≤10 条/10min** | 同上，窗口聚合 | 不能（无窗口聚合） |
| 洪泛时间占比 | 洪泛时长 ÷ 总运行时长 | **<1%** | 需按上述定义算 | 不能 |
| Standing alarms | 持续 active 超过 1 个班的报警数 | **<10** | `resolved_at is null` + 时长 | 能（缺“超过 1 班”口径） |
| Stale alarms | active 超过 24h 的报警数 | **<5**（最好 0） | 同上 | 能 |
| 抖动报警数 | 1 分钟内 ≥3 次置位/复位的测点数 | **<5** | 需状态变迁表 | 不能（只有结果表） |
| 优先级分布 | P1/P2/P3/P4 占比 | **≈5/15/80**（P4 可并入） | 需新增 priority 字段 | 不能（只有 level） |
| 确认率 | 已确认 ÷ 总数 | **>95%** | `acked_at` | 能 |
| 平均确认时长 | avg(acked_at − started_at) | P1 **≤1min**、P2 ≤5min | `acked_at` | 能（`ack_avg_min`） |
| 平均处置时长 | avg(closed_at − started_at) | 按等级定 | `closed_at` | 能（`alarm_close_avg_min`） |
| 误报率 | resolution=misreport ÷ 已关闭 | **<10%** | `resolution` | 能（有 misreport 枚举） |
| 搁置率/时长 | 搁置数 ÷ 总数；平均搁置时长 | 搁置率 **<5%**，单次 ≤8h | 需新增字段 | 不能 |
| 抑制数 | 按设计抑制的点位数 | 有清单、可审计 | 需新增 | 不能 |
| Top-N 最吵 | 按测点/设备统计报警数 | 前 10 名必须被合理化 | `metric` 分组 | 能（`by_metric`） |
| 告警→工单时长 | avg(工单 created_at − 报警 started_at) | 按等级 | `work_order.source_id` | 能（`alarm_to_order_avg_min`） |

### 3.6 我们差在哪（具体到字段/文件）

| 缺口 | 现状 | 最小改法 | 工作量 |
|---|---|---|---|
| 优先级 | `alarm_record.level` 只有 warn/critical | 加 `priority`（1–4）+ `priority_reason`；配置表「指标→后果→时限→优先级」 | 1.5 人日 |
| 搁置 | 无 | `alarm_shelve` 表 + 4 个接口（搁置/解除/清单/到期扫描）+ 前端弹窗与角标 | 2.5 人日 |
| 死区/延时 | `alarms.py` 单阈值比较 | `sensor`/规则加 `deadband`、`on_delay_s`；判定改状态机 | 2 人日 |
| 首出/因果 | 无 | 规则加 `suppresses[]`（A 抑制 B）；同组只报首条 | 2 人日 |
| 抖动/洪泛 | 只有 `dedupe_s=60` + 3 次升级 | 状态变迁表 `alarm_transition`；窗口聚合任务；看板 | 2 人日 |
| KPI | 报表有 8 个告警指标 | 增加上表 6 个；口径写进文档；日报/周报 | 1.5 人日 |

---

## 4. 任务与工单的行业范式

### 4.1 五个概念必须分开（现在是混的）

| 概念 | 回答什么问题 | 关键指标 | 我们的实体 |
|---|---|---|---|
| **巡检计划** | 什么时候、按什么路线、查哪些点 | 计划完成率 | `inspection_plan` |
| **巡检任务** | 这一次谁去、查到没有 | **到位率**、漏检率 | `inspection_task` / `task_run` |
| **告警** | 现在有什么异常 | 报警率、确认时长 | `alarm_record` |
| **缺陷** | 设备哪里坏了、多严重 | 缺陷率、定级分布 | **无**（混在 work_order） |
| **工单** | 谁去修、多久修好 | 消缺及时率、超期率 | `work_order` |

> 工业级平台一定把「缺陷」独立出来：因为缺陷要**定级**（紧急/重大/一般）、要**挂设备**、要**统计重复缺陷**、要**走消缺流程**。工单只是缺陷的处置载体。

### 4.2 缺陷定级与时限（有明文依据，可直接写进合同）

| 等级 | 定义（南网口径） | 处置时限 | 行业制度（参考） | 平台字段 |
|---|---|---|---|---|
| 紧急/危急 | 直接威胁安全运行，随时可能造成设备损坏、人身伤亡、大面积停电、火灾 | **立即**安排处理 | **24 小时内** | `severity=urgent`、`resolve_due_at` |
| 重大/严重 | 对人身、电网、设备有严重威胁，尚能坚持运行，不及时处理可能造成事故 | **一周内** | 按甲方 | `severity=major` |
| 一般 | 短时不会发展为重大/紧急，对运行有影响但能坚持运行 | **半年内** | 按甲方 | `severity=minor` |

来源：[南方电网公司变电运行管理标准·设备管理](https://tech.bjx.com.cn/html/20071227/57964.shtml)（缺陷分三类、紧急立即/重大一周/一般半年、流程为**发现→报告→受理分析→处理→验收→反馈**六环节）；[变电站设备缺陷管理制度](http://p.safehoo.com/Manage/System/Electric/201411/372376.shtml)（危急缺陷处理不得超过 24 小时）。

**这张表的价值**：它把“SLA”从拍脑袋变成了**可配置的等级→时限映射**。验收问“超时怎么办”，你答“紧急立即、重大 7 天、一般 180 天，超时自动升级并计入消缺及时率”，比答“我们有 due_at”强十倍。

### 4.3 派单规则（工业级是规则，不是下拉框）

| 规则 | 触发 | 逻辑 | 优先级 | 我们的现状 |
|---|---|---|---|---|
| 技能匹配 | 新建工单 | 工单类型 → 所需资质（电气/仪表/防爆/机器人）→ 有资质的人 | 最高 | 无（`assignee_id` 手工选） |
| 区域就近 | 同上 | 按 `area_id` 匹配责任班组，减少到场时间 | 高 | 无（只有 `station` 字符串） |
| 班次值班 | 同上 | 只派给当前班次在岗的人 | 高 | 无（有 `shift` 字段但不用） |
| 负荷上限 | 同上 | 每人同时在手工单 ≤N（如 5），超了顺延 | 中 | 无 |
| 设备责任人 | 同上 | 设备台账 `owner_id` 优先 | 中 | 无（台账没这字段） |
| 回避规则 | 同上 | 上一轮处置人被投诉/返工的，本轮回避 | 低 | 无 |
| 合并 | 同设备多条告警 | N 条告警合并 1 张工单，明细挂子项 | 高 | 无（告警→工单是 1:1） |
| 转派/退回 | 处置中 | 转派需理由；退回需班长确认 | 中 | 无 |
| 抢单 | 可选 | 班组内先到先得，超时回退到派单 | 低 | 无 |

**最小可落地版**（不上一堆规则引擎）：`work_order` 加 `required_skill`、`area_id`、`sla_level`；派单接口支持「按技能+区域+在岗」自动推荐 Top3，人工确认。这就够验收演示，也不至于过度设计。

### 4.4 SLA 与升级策略（时间轴要能画出来）

| 阶段 | 起算点 | 目标 | 超时动作 | 字段 |
|---|---|---|---|---|
| 响应（接单） | 告警产生/工单创建 | P1 1min、P2 5min、P3 30min | 通知班长；P1 同时通知安全员 | `accepted_at`、`response_due_at` |
| 到场 | 接单 | P1 5min、P2 30min、P3 当班 | 通知厂长；记录迟到 | `arrived_at`、`arrive_due_at` |
| 处置（消缺） | 到场 | 紧急立即、重大 7d、一般 180d | 升级 + 计入超期 | `resolved_at`、`resolve_due_at` |
| 复核 | 处置完成 | 24h 内 | 通知发起人；超期未复核 → 自动升级 | `reviewed_at`、`reviewer_id` |
| 关闭 | 复核通过 | — | — | `closed_at`、`closed_by` |

**挂起（pause）必须支持**：等备件、等停电窗口、等厂家——否则“消缺及时率”会被这些合法等待拖死。挂起要**理由 + 预计恢复时间 + 审批**，且挂起时长单独统计（不计入 SLA，但计入总时长）。

**升级时间轴（P1 示例）**：

```
T+0     报警产生 → 值班员（App/短信/电话）
T+1min  未确认 → 班长
T+3min  未确认 → 厂长 + 安全员
T+5min  未到场 → 厂长 + 甲方接口人
T+30min 未控制 → 启动应急预案（平台只记录，不代替预案）
```

### 4.5 闭环证据：验收真正看的东西

| 证据 | 采集方式 | 存储 | 不可篡改 | 我们的现状 |
|---|---|---|---|---|
| 时间戳 | 服务端时间（NTP） | DB | 审计链 | 有（未强制 NTP） |
| 位置 | 点位 ID / 机器人位姿 / 手机 GPS | DB | 同上 | 有（点位；手机 GPS 不确定） |
| 照片 | 机器人相机/手机 | 本地目录 | **无**（可被删改） | 有（`photos_json`），无哈希 |
| 视频片段 | 告警前后 N 秒 | go2rtc/ffmpeg | **无** | 无（只有直播/连续录像） |
| 读数 | 传感器/AI 结果 | DB | 有 | 有（`value_json`、`/ai/results`） |
| AI 置信度 | 算法返回 | DB | 有 | 有（`ai.py`），未在工单展示 |
| 处置人签名 | 账号+口令/MFA 再确认 | DB | 审计链 | 弱（只有 `handled_by`） |
| 复核人签名 | 同上 | DB | 审计链 | 无 |
| 备件/工时 | 手工填 | DB | 有 | 无 |
| 导出包 | zip + manifest + sha256 | 本地/NAS | 可校验 | 无 |

**验收话术**：不要只说“我们有照片”。要说“每条巡检记录绑定点位、时间、执行人、照片 sha256、关联告警/工单，导出 zip 带 manifest，可离线校验”。这一句能覆盖“巡检造假”“证据缺失”两类质疑。

---

## 5. 权限与审计：三权分立之外，工业现场还有什么

### 5.1 现有角色与现场惯例的映射

| 我们的角色 | 现场对应 | 缺什么 |
|---|---|---|
| `admin` | （应取消日常使用） | 超级用户是审计黑洞 |
| `sysadmin` | 系统管理员 | — |
| `secadmin` | 安全管理员 | 应管账号/权限/证书，不管业务 |
| `auditor` | 审计员 | 只读 + 可导出，不能改 |
| `safety` | 安全员/安监 | 应能**叫停**任务、强制升级 P1 |
| `operator` | 值班员 | 应受“班次/区域”限制 |
| `viewer` | 访客/领导 | — |

**三权分立之外，工业现场还有 6 条惯例**：

| 惯例 | 现场怎么做 | 平台应有什么 | 我们的现状 |
|---|---|---|---|
| **工作票** | 第一种（停电/高危）/第二种（不停电）；签发人、许可人、负责人、终结 | `work_ticket`：类型、安全措施、签发/许可/终结、关联设备与工单 | 无 |
| **操作票** | 倒闸/启停步骤逐项唱票复诵，监护人打勾，最后“已执行”章 | `operation_ticket` + `operation_step`：步骤、顺序、监护人、执行时间、异常中止 | 无 |
| **双人复核** | 操作人 + 监护人；高危动作需许可 | 高危动作 `require_approval`：申请人≠审批人，审批留痕，超时失效 | 无 |
| **交接班** | 班前会、交接记录、未完成事项移交、双方签字 | `shift_handover`：班次、交接人/接班人、未闭环告警/工单、遗留风险、签名 | 无（只有 `shift` 字段） |
| **巡回检查/定期轮换** | 定时按路线巡、备用设备定期切换试验 | 巡检计划 + 定期试验计划 + 到期提醒 | 部分（巡检计划有，试验无） |
| **LOTO 上锁挂牌** | 检修时断电上锁，谁锁谁开 | 设备状态 `lockout` + 锁定人 + 解锁审批 | 无 |

### 5.2 高危动作清单（必须双人复核或强提示）

| 动作 | 风险 | 建议要求 | 现状 |
|---|---|---|---|
| 下发/取消机器人任务 | 撞人/撞设备 | 二次确认；P1 告警期间禁止自动下发 | 有确认，无互锁 |
| 急停复位 | 带病运行 | **双人复核**（操作人+安全员） | 无 |
| 修改告警阈值 | 掩盖故障 | 双人复核 + 变更记录 + 生效时间 | 无（`admin/safety` 可改） |
| 搁置 P1 告警 | 漏报 | 班长审批 + ≤30min | 无（无搁置） |
| 删除录像/审计 | 毁证 | 禁止硬删；软删 + 审批 + 保留期 | 弱 |
| 导出数据 | 泄密 | 水印 + 留痕 + 次数限制 | 弱 |
| 改点位坐标 | 车走错 | 双人复核 + 残差校验 | 有残差阈值，无复核 |
| 改角色/授权 | 提权 | 双人复核 + 定期复核 | 无 |
| 升级固件 | 变砖 | 维护窗口 + 回滚包 | 无 |

### 5.3 审计要做到什么程度

| 要求 | 工业/等保口径 | 我们的现状 | 最小补法 |
|---|---|---|---|
| 覆盖 | 所有写操作、登录、导出、审批、配置变更 | 有 `operation_log` + 哈希链 | 补“导出/审批/搁置”事件 |
| 字段级 | 改前/改后值 | 只有 action/target | 加 `before_json/after_json`（脱敏） |
| 不可篡改 | WORM/异地/定期锚定 | 哈希链同库，DBA 可重算 | 每日哈希锚定到外部（时间戳/邮件/另一台机） |
| 留存 | 法规要求网络日志 ≥6 个月，等保测评按此查 | 永久，但无归档 | 180 天热 + 归档冷 |
| 可检索 | 按人/时间/对象/动作 | 有基础筛选 | 加 request_id 串联 |
| 导出 | 可读、可校验 | 有 CSV/接口 | 导出带签名与校验说明 |
| 双人 | 高危动作审批链 | 无 | 见 §5.2 |

> 电子记录/电子签名的严肃版本可参考 [FDA 21 CFR Part 11](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/part-11-electronic-records-electronic-signatures-scope-and-application)：唯一账号、审计追踪、记录不可篡改、签名与记录绑定。医药/食品客户会直接拿这个问。

---

## 6. 设备档案/资产台账：比 `robot` 表多什么

### 6.1 先补层级（ISA-95 设备层级）

| ISA-95 | 现场叫法 | 我们的对应 | 结论 |
|---|---|---|---|
| Enterprise | 集团 | 无 | 不做 |
| Site | 场站/厂区 | `station`（字符串） | 需实体化 |
| Area | 区域/装置/防爆区 | 无 | **必须补**（报表按区域聚合、权限按区域隔离） |
| WorkCenter | 设备/机组 | `robot` / `sensor` / `camera` | 有，但分散在多表 |
| WorkUnit | 部件/测点/点位 | `point_draft`、`peripheral` | 部分 |

**HA 的 Area/Floor/Label 模型值得直接借**：区域是物理位置，标签是多对多（同一设备可同时是“防爆区”“A 班”“关键设备”），实体可继承设备区域也可覆盖。见 [Home Assistant: Grouping your assets](https://www.home-assistant.io/docs/organizing/)。

### 6.2 台账字段全表（★=防爆场景验收必问）

| 组 | 字段 | 说明/示例 | 为什么工业级必须有 | 我们有没有 |
|---|---|---|---|---|
| 身份 | `asset_code` ★ | 位号，如 `P-101A` | 现场沟通、工单、图纸全靠位号 | 无（只有 `id`/`name`） |
| 身份 | `asset_type` | 机器人/相机/传感器/门禁/PLC/仪表 | 分类统计与权限 | 部分（`device_type`） |
| 身份 | `manufacturer` / `model` / `serial_no` ★ | 厂商/型号/序列号 | 备件、维保、召回 | 只有 `version` |
| 身份 | `parent_id` / `area_id` | 层级关系 | 聚合与隔离 | 无 |
| 位置 | `site` / `area` / `zone` ★ | 厂区/装置/**防爆区域 Zone 0/1/2、21/22** | 准入判断、巡检路线 | 只有 `station` |
| 位置 | `install_date` / `commission_date` ★ | 安装/投运日期 | 折旧、寿命、维保起算 | 无 |
| 位置 | `coord_x/y/z` / `map_id` | 坐标与地图 | 导航与展示 | 点位有，设备无 |
| 技术 | `protocol` / `endpoint` / `port` | Modbus/OPC UA/HTTP/MQTT | 接入与排障 | 部分（`ip/port/mode`） |
| 技术 | `ip` / `mac` / `vlan` / `cert` | 网络与证书 | 安全分区、资产测绘 | 部分 |
| 技术 | `firmware` / `software_version` | 固件/软件版本 | 漏洞与升级管理 | `version` |
| 技术 | `power` / `battery` / `endurance_h` | 供电/续航 | 任务排期 | 无 |
| 能力 | `capabilities[]` | 可执行动作（拍照/测温/气体/声学/操作） | 任务编排与算法匹配 | `capabilities_json` |
| 能力 | `detection_items[]` | 检测项（表计/阀门/跑冒滴漏/人员着装） | 巡检项与 AI 算法绑定 | 无 |
| **防爆** | `ex_marking` ★★ | `Ex d IIC T6 Gb / Ex tb IIIC T80℃ Db` | 准入与合规 | **无** |
| **防爆** | `ex_cert_no` / `ex_cert_expiry` ★★ | 防爆合格证编号与有效期 | 验收必查、到期提醒 | **无** |
| **防爆** | `temp_class` / `gas_group` ★ | T6 / IIC | 区域匹配 | **无** |
| **防爆** | `ip_rating` | IP66/IP68 | 冲洗/户外 | **无** |
| 合规 | `inspection_cert` / `calibration_cycle` / `next_calibration` ★ | 检定/校准周期 | 计量法要求、到期提醒 | **无** |
| 合规 | `safety_level`（SIL/PL） | 功能安全等级 | 安全回路边界 | 无 |
| 运维 | `owner_id` / `team` / `shift` | 责任人/班组 | 派单 | 无 |
| 运维 | `maintain_contract` / `warranty_until` ★ | 维保合同/质保到期 | 到期提醒、费用 | 无 |
| 运维 | `spare_parts[]` / `criticality` | 备件/关键度 | 备件计划、优先级 | 无 |
| 运维 | `mtbf_h` / `mttr_h` / `health_score` | 可靠性指标 | 报表与预测 | 无 |
| 生命周期 | `status` | 在用/闲置/维修/停用/报废 | 统计口径、任务排除 | 只有 `is_active` |
| 生命周期 | `retire_date` / `scrap_reason` | 退役 | 资产核销 | 无 |
| 文档 | `manual` / `drawing` / `cert_file` | 说明书/图纸/证书 PDF | 现场排障、验收 | 无 |
| 变更 | `change_log[]` | 谁改了什么 | 审计 | 审计表有，未挂资产 |
| 关系 | `related_assets[]` | 上下游/联动设备 | 因果抑制、联锁 | 无 |
| 关系 | `points[]` | 巡检点位 | 任务编排 | 有（`point_draft`） |

**差距量化**：`robot` 表现在 **21 个字段**；上表工业级最小集约 **45–50 个字段**，其中防爆/检定/维保/层级/位号/文档是**零覆盖**。这不是“字段多一点”，是**从“联网设备”变成“受监管资产”**。

### 6.3 最小数据模型（不推翻现有表，做扩展）

```sql
-- 1) 区域（补 ISA-95 Area）
CREATE TABLE area (
  id INT PRIMARY KEY,
  site_id INT NOT NULL,
  parent_id INT NULL,
  name VARCHAR(64) NOT NULL,
  kind VARCHAR(16),          -- area/workshop/explosion_zone
  zone_class VARCHAR(16),    -- Zone 0/1/2, 21/22
  geom_json TEXT,            -- 多边形，用于电子围栏
  created_at DATETIME
);

-- 2) 资产扩展（与 robot/sensor/camera 1:1，不破坏现有表）
CREATE TABLE asset_profile (
  asset_table VARCHAR(16) NOT NULL,   -- robot/sensor/camera/peripheral
  asset_id INT NOT NULL,
  asset_code VARCHAR(32) NOT NULL,    -- 位号
  area_id INT NULL,
  manufacturer VARCHAR(64), model VARCHAR(64), serial_no VARCHAR(64),
  ex_marking VARCHAR(64), ex_cert_no VARCHAR(64), ex_cert_expiry DATE,
  ip_rating VARCHAR(16),
  calibration_cycle_days INT, next_calibration DATE,
  warranty_until DATE, maintain_contract VARCHAR(64),
  owner_id INT, team VARCHAR(32),
  criticality TINYINT, status VARCHAR(16),
  commission_date DATE, retire_date DATE,
  PRIMARY KEY (asset_table, asset_id),
  UNIQUE KEY uk_code (asset_code)
);

-- 3) 文档与变更
CREATE TABLE asset_doc (
  id INT PRIMARY KEY, asset_table VARCHAR(16), asset_id INT,
  kind VARCHAR(16),           -- manual/drawing/cert/photo
  file_path VARCHAR(255), sha256 CHAR(64), uploaded_by INT, created_at DATETIME
);

-- 4) 缺陷（从 work_order 拆出来）
CREATE TABLE defect (
  id INT PRIMARY KEY,
  asset_table VARCHAR(16), asset_id INT,
  severity VARCHAR(8),        -- urgent/major/minor
  found_by INT, found_at DATETIME, source VARCHAR(16),  -- robot/manual/ai/alarm
  description TEXT, photos_json TEXT,
  status VARCHAR(16),         -- open/assigned/fixed/verified/closed
  resolve_due_at DATETIME,
  work_order_id INT NULL,
  repeat_of INT NULL,         -- 重复缺陷指向原缺陷
  created_at DATETIME
);
```

> 迁移策略：**expand 不 replace**。先加表加字段、双写、老接口不变；报表切新表；一个版本后再删旧字段。不要在一次上线里改 `robot` 主键。

---

## 7. 数据与报表：行业通行的报表种类

### 7.1 报表分类（按“谁会看”分，比按“数据源”分有用）

| 类别 | 报表 | 关键指标/公式 | 读者 | 周期 | 我们的现状 |
|---|---|---|---|---|---|
| 运行 | 设备运行日报 | 在线率 = 在线时长 ÷ 应在线时长；可用率 = (总时长−故障时长) ÷ 总时长 | 值班/运维 | 日 | 有在线率（按遥测样本） |
| 运行 | 机器人效能 | 日均任务数、日均点位、里程、充电次数、单任务耗时 | 运维/甲方 | 周/月 | 有里程/电量；无单任务耗时 |
| 巡检 | **巡检计划完成率** | 完成任务数 ÷ 计划任务数 | 班长 | 日/周 | 有（按人 done_rate） |
| 巡检 | **巡检到位率/漏检率** ★ | 实际打点 ÷ 应打点；漏检 = 1 − 到位率 | 甲方/安监 | 周/月 | **无**（只有点位覆盖率与模板覆盖） |
| 巡检 | 巡检及时率 | 按计划时间窗完成 ÷ 总任务 | 班长 | 周 | 无 |
| 巡检 | 人均巡检量 | 点位数 ÷ 在岗人数 ÷ 天数 | 管理者 | 月 | 部分（按人 items） |
| 缺陷 | **缺陷发现率** | 缺陷数 ÷ 巡检点位数（或 ÷ 千点位） | 运维 | 月 | **无**（无缺陷实体） |
| 缺陷 | 缺陷定级分布 | 紧急/重大/一般 占比 | 管理者 | 月 | 无 |
| 缺陷 | **消缺率** | 已消缺 ÷ 发现缺陷 | 甲方 | 月 | 部分（工单 closed/total） |
| 缺陷 | **消缺及时率** ★ | 按期消缺 ÷ 应消缺 | 甲方 KPI | 月 | **无**（无等级→时限） |
| 缺陷 | 重复缺陷率 | 同一设备同类缺陷重复次数 ÷ 总缺陷 | 技术 | 季 | 无 |
| 缺陷 | 超期未消缺 | 超 `resolve_due_at` 且未关闭 | 管理者 | 日 | 部分（`due_at` 超期） |
| 告警 | 告警日报 | 分级数量、Top-N 最吵、确认/处置时长 | 值班 | 日 | 有基础（8 指标） |
| 告警 | **报警治理月报** | §3.5 全部 KPI | 管理者/甲方 | 月 | 缺 6 项 |
| 工单 | 工单效率 | 派单量、及时响应率、超时率、升级率、返工率 | 班长 | 周/月 | 部分（闭环率/时长） |
| 资产 | 台账完整性 | 必填字段完整率（按资产类型） | 管理者 | 月 | 无 |
| 资产 | **到期预警** | 防爆证/检定/维保/质保到期清单 | 设备员 | 日/周 | **无** |
| 视频 | 录像可用率 | 有效录像时长 ÷ 应录时长 | 运维 | 周 | 无 |
| 合规 | 审计完整性 | 哈希链校验通过率、异常条数 | 审计员 | 月 | 有（`/audit-logs/verify`） |
| 合规 | 交接班执行率 | 已交接班次 ÷ 应交接班次 | 管理者 | 月 | 无 |
| 合规 | 两票执行率 | 有票作业 ÷ 总作业 | 安监 | 月 | 无 |
| 事件 | 事件报告 | 单次事件时间线、证据、处置、根因 | 甲方/安监 | 触发 | 无 |
| 验收 | 验收证据包 | 指标 + 审计 + 录像 + 配置快照 | 甲方 | 一次性 | 无 |

★ = 甲方运维考核表里高频出现、我们完全没有的。**注意**：前四项“巡检/缺陷”类，是巡检平台的**立身之本**；我们现在报表强在“告警/工单”，弱在“巡检/缺陷”——这是定位偏差，不是功能遗漏。

### 7.2 口径陷阱（写进文档，避免验收时各算各的）

| 指标 | 常见错法 | 正确口径 | 要在哪写清 |
|---|---|---|---|
| 在线率 | 用“有心跳的样本 ÷ 总样本”，把夜间停机也算离线 | **应在线时长**为分母（按排班/计划），维护窗口剔除 | 报表脚注 + 合同 |
| 巡检到位率 | 用“任务完成”代替“点位到位” | 分母是**计划点位数**，分子是**实际打点且有证据**的点位 | 报表定义页 |
| 消缺及时率 | 从“派单时间”起算 | 从**缺陷发现时间**起算；挂起时长单列 | 报表定义页 |
| 缺陷率 | 缺陷数 ÷ 巡检次数 | 缺陷数 ÷ **巡检点位数**（千点位缺陷数） | 报表定义页 |
| 告警数 | 含重复/抖动/搁置 | 去重后、排除搁置与设计抑制 | 告警 KPI 页 |
| 平均确认时长 | 只算已确认的（幸存者偏差） | 同时给“未确认占比”和“P95” | 报表脚注 |
| MTBF | 用日历时间 ÷ 故障次数（含停机） | **运行时间** ÷ 故障次数 | 报表定义页 |

### 7.3 报表交付形态（施耐德 PME 的做法值得抄）

| 形态 | 说明 | 我们的现状 | 建议 |
|---|---|---|---|
| 页面看板 | 可配置仪表盘、Kiosk 视图 | 有 Vue 报表页 | 加“报表订阅”入口 |
| 手动生成 | 选区间 → 预览 → 导出 | 有 `/reports/summary` + `/export.xlsx` | 加 PDF（带页眉/签章位） |
| **定时订阅** | 每日 08:00 发值班群/邮件 | 无 | 复用 `notify` 渠道 |
| **事件触发** | 告警关闭/工单超期时自动出单页报告 | 无 | 事件钩子 + 模板 |
| 多格式 | PDF/HTML/CSV/XLSX | 只有 XLSX | 加 PDF/CSV |
| 对外 API | 甲方 BI 拉数 | 有 OpenAPI | 加只读聚合接口 + 限流 |

> 施耐德 PME 的公开说明：30+ 预置报表，**手动/定时/事件触发**三种触发方式，输出 **PDF/HTML/CSV**，看板可配置并可嵌入外部页面（[PME Reporting](https://product-help.se.com/docs/EcoStruxure/Power-Operation-2022/content/2_planning/pme/advrprtnganddash.htm)）。这几条是“报表模块成熟度”的硬指标，不是花活。

---

## 8. 我们最缺的 10 项（按“验收会被追问”排序）

> 排序依据：① 验收现场被问到的概率；② 答不上来的后果（扣分/整改/验收不通过）；③ 是否是“没有就说不清”的根基项。
> 现状证据只引代码，不引“计划”。

| # | 缺口 | 验收会怎么问（原话） | 现状证据 | 最小补法 | 人日 | 不补的后果 |
|---|---|---|---|---|---|---|
| **1** | **告警治理（分级/搁置/泛滥/KPI）** | “一天报多少条？P1 会不会被淹？检修时能不能先别报？屏蔽了谁负责？” | `alarm_record.level` 只有 warn/critical；`alarms.py` 仅 60s 去重 + 3 次升级；无 shelve/deadband/首出 | 加 `priority`+`alarm_shelve` 表+死区/延时+首出抑制+6 个 KPI；见 §3.6 | **11.5** | 值班被淹没→真报警被忽略→事故；验收“告警有效性”直接挂 |
| **2** | **巡检闭环证据链** | “凭什么证明这个点巡过了？照片能不能删？和告警对得上吗？” | `task_run_step` 有 status；`photos_json` 存路径无哈希；无事件录像；导出无 manifest | 照片 sha256 + 点位/时间/人绑定；事件录像前后 10/30s；导出 zip+manifest | **6** | “巡检造假”质疑无法反驳；争议时无证据 |
| **3** | **防爆资产台账** | “Ex 证书呢？区域等级？检定到期了没？谁负责？” | `robot` 21 字段，无 ex_marking/cert/area/owner/calibration | `asset_profile` + `area` 表；到期提醒；台账完整率报表 | **5** | 防爆场景**直接不合格**；这是最容易补、最不该缺的 |
| **4** | **SLA / 派单 / 升级可配置** | “超时怎么办？派给谁？班组怎么分？挂起算不算超时？” | `work_order` 有 `due_at`/`escalated_at`，`due_hours` 写死；`assignee_id` 手工 | 等级→时限映射表；技能/区域/在岗推荐；挂起与暂停；升级时间轴 | **5** | “有工单没 SLA”，甲方运维考核对不上 |
| **5** | **行业报表口径** | “巡检到位率多少？缺陷率？消缺及时率？MTBF？” | `/reports/summary` 有 20+ 指标，但无到位率/缺陷率/消缺及时率/MTBF | 拆 `defect` 表；补 6 个指标；口径写进报表页脚 | **4** | 报表“看着全”，一问关键指标就哑 |
| **6** | **双人复核 / 操作票 / 交接班** | “急停复位谁批的？夜班交接记录呢？操作票呢？” | 7 角色齐，但无审批流、无 `shift_handover`、无操作票 | 高危动作 `require_approval`；交接班表；操作票步骤表（可先只做“记录”） | **6** | 电力/石化甲方认为“不懂现场”；审计追问审批链断裂 |
| **7** | **事件录像与视频证据包** | “报警那一刻的视频呢？能导出来吗？存多久？” | go2rtc 2 路连续录像；`camera_id` 已固化到告警；无片段/索引 | 告警触发保存前 10s/后 30s；`manifest.json`（alarm_id/camera/起止/sha256） | **2.5** | “有视频”但找不到那一刻；工单证据不完整 |
| **8** | **审计外锚与不可篡改** | “审计日志谁能改？DBA 改了呢？导出能验吗？” | 哈希链同库；`0017_rechain_audit.py` 曾整表重算 | 每日哈希锚定外部（时间戳/邮件/另一台机）；字段级 diff；导出签名 | **3** | 等保/事后追责时“自证清白”不成立 |
| **9** | **多场站数据隔离与对象级权限** | “A 厂的人能看到 B 厂吗？区域权限怎么分？” | 7 角色全局；`station` 是字符串；无 `area_id`/数据范围 | `area` 表 + 用户 `data_scope`；查询强制过滤；越权审计 | **4** | 多场站项目无法交付；单场站也会被问“扩展性” |
| **10** | **可证明的可靠性** | “断电/拔网线/数据库挂了会怎样？RTO/RPO 多少？演练记录呢？” | 单机单库；本地 dump 14 天；无异地/无生产恢复演练 | 备份加密+异地+每周恢复演练；断网/停库/停录三类演练报告 | **5** | 一次故障=交付事故；验收“可靠性”项无证据 |

**合计约 52 人日**（含自测与文档，不含真机联调等待）。如果只有 10 人日：**#3 防爆台账（5）→ #1 的分级与搁置（4）→ 口径文档（1）**。理由：这三项都能在验收现场**当场演示**，且都不依赖真机。

### 8.1 分档建议

| 预算 | 做哪些 | 能换来什么 |
|---|---|---|
| 10 人日 | #3 防爆台账（5）+ #1 的分级与搁置（4）+ 口径文档（1） | 验收最容易被问的“Ex 证书/告警怎么分级/能不能屏蔽”有答案 |
| 25 人日 | #1（11.5）+ #2（6）+ #3（5）+ #7（2.5） | 告警治理、证据链、防爆台账、事件录像四段成型 |
| 50 人日 | #1–#9（47），余 3 人日做演练与文档；#1–#10 约 52 | 可投“工业级”标，但**仍不要碰** HA/时序库/GB28181/VDA5050 |

### 8.2 明确不做（写进偏离表，别让它变成隐性承诺）

| 项 | 为什么不做 | 怎么说 |
|---|---|---|
| 3D 数字孪生 | 演示价值 > 交付价值；一期无数据支撑 | “二期可选，按需报价” |
| 自研 SLAM/导航 | 厂商核心能力，平台重复造轮子 | “平台不承担导航与安全回路” |
| 自研时序库/NVR/对象存储 | 运维成本远超收益 | “采用成熟组件，二期评估” |
| VDA5050 合规认证 | 需 conformance 用例与厂商配合 | “借消息模型，不声称合规” |
| 多租户 SaaS | 单站点交付，租户模型会拖慢一切 | “单站点部署，多场站用区域隔离” |
| 平台级急停 | 功能安全边界 | “急停由本体安全回路负责，平台只记录与联动” |

### 8.3 验收现场速查卡（被问到就照这张答）

| 追问 | 一句话回答 | 证据在哪 |
|---|---|---|
| “一天报多少条告警？” | “按人按班统计，目标 ≤6 条/小时；现在能给确认/处置时长和 Top-N 最吵测点，泛滥 KPI 在补。” | `/reports/summary` 的 `response_metrics`、`by_metric` |
| “P1 会不会被淹？” | “P1 红色连续声、1 分钟未确认升班长；洪泛期只显示 P1/P2，其余折叠计数。” | 待补（§3.5 看板） |
| “检修时能不能别报？” | “能搁置，必须填理由，最长 8 小时，到期自动恢复，全程留痕；P1 需班长批。” | 待补（`alarm_shelve`） |
| “凭什么证明巡过了？” | “点位+时间+执行人+照片 sha256+关联告警/工单，导出带 manifest 可离线校验。” | `task_run_step`、导出包 |
| “照片会不会被删？” | “录像/照片落盘即算哈希，删改会被发现；审计里能查到导出记录。” | 待补（sha256 + 审计） |
| “Ex 证书呢？区域等级？” | “台账有位号、Ex 标志、证书号与有效期、Zone 等级，到期前 30 天预警。” | 待补（`asset_profile`） |
| “超时怎么办？” | “紧急立即、重大 7 天、一般 180 天；超时自动升级到班长/厂长并计入及时率。” | `work_order.due_at` + §4.4 |
| “派给谁？怎么分？” | “按技能+区域+在岗推荐 Top3，人工确认；同设备多条告警合并一张单。” | 待补（§4.3） |
| “夜班交接记录呢？” | “交接班表：班次、交接/接班人、未闭环告警工单、遗留风险、双方签名。” | 待补（`shift_handover`） |
| “急停复位谁批的？” | “双人复核，操作人≠复核人，审批链进审计。” | 待补（§5.2） |
| “拔网线会怎样？” | “3 秒标数据过期、10 秒出离线告警、恢复自动重连；有演练记录。” | `StateCache` + 演练报告 |
| “数据库挂了 RTO 多少？” | “每日加密备份+异地，RTO 1 小时、RPO 24 小时，每周真实恢复演练。” | 待补（备份 runbook） |
| “审计日志谁能改？” | “哈希链+每日外锚，DBA 改不了外部锚点；导出可校验。” | `/audit-logs/verify` + 待补外锚 |
| “A 厂能看到 B 厂吗？” | “按区域做数据范围，看不到；越权有审计。” | 待补（`area` + `data_scope`） |

> 这张表建议直接做成验收答辩的一页纸：**左边是甲方原话，右边是我们能指着屏幕说的东西**。答不上来的，就是 §8 里那 10 项。

---

## 9. 链接总表（核对日期 2026-10-23）

| 类型 | 对象 | 链接 | 核对结果 |
|---|---|---|---|
| 商用 | 海康 iVMS-8700 | https://product.asmag.com.cn/46085.html | 可访问；官网产品页 404，用 a&s 产品库 |
| 商用 | 申昊 L4-G2 防爆巡检机器人 | https://www.shenhaoinfo.com/l4-g2-shir-4000ex-%e9%98%b2%e7%88%86%e8%bd%ae%e5%bc%8f%e5%b7%a1%e6%a3%80%e6%9c%ba%e5%99%a8%e4%ba%ba/ | 可访问，参数取自页面 |
| 商用 | 亿嘉和 SI300 | https://www.yijiahe.com/robot-si300 | 可访问；平台模块未公开 |
| 商用 | 国自 InView | https://www.gzrobot.com/intelligentInspection/software | 可访问 |
| 商用 | 西门子 SIMATIC PCS 7 | https://www.siemens.com/en-us/products/process-control/simatic-pcs-7/ | 可访问（旧 URL 404） |
| 商用 | 施耐德 PME 报表/看板 | https://product-help.se.com/docs/EcoStruxure/Power-Operation-2022/content/2_planning/pme/advrprtnganddash.htm | 可访问 |
| 开源 | ThingsBoard device profiles | https://thingsboard.io/docs/user-guide/device-profiles/ | 可访问 |
| 开源 | ThingsBoard assets | https://thingsboard.io/docs/user-guide/assets/ | 可访问 |
| 开源 | ThingsBoard alarms | https://thingsboard.io/docs/user-guide/alarms/ | 可访问 |
| 开源 | ThingsBoard rule engine | https://thingsboard.io/docs/user-guide/rule-engine-2-0/overview/ | 文档结构，链接有效 |
| 开源 | Home Assistant 组织模型 | https://www.home-assistant.io/docs/organizing/ | 可访问，Area/Floor/Label 已核 |
| 开源 | Open-RMF | https://openrmf.readthedocs.io/en/latest/ | 可访问，task queuing/resource scheduling 已核 |
| 开源 | VDA5050 v3.0.0 | https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md | 原文可访问（raw 可取） |
| 开源 | FUXA | https://github.com/frangoteam/FUXA | 仓库链接；本次抓取失败，按已知项目引用 |
| 开源 | OpenSCADA | https://oscada.org/ | 站点存在；本次抓取失败 |
| 开源 | Grafana | https://grafana.com/docs/grafana/latest/ | 官方文档 |
| 开源 | Node-RED | https://nodered.org/docs/ | 官方文档 |
| 规范 | ISA-18 系列 | https://www.isa.org/standards-and-publications/isa-standards/isa-18-series-of-standards | 可访问 |
| 规范 | ANSI/ISA-18.2-2016 | https://www.isa.org/products/ansi-isa-18-2-2016-management-of-alarm-systems-for | 可访问 |
| 规范 | ISA-TR18.2.3 基础报警设计 | https://www.isa.org/products/isa-tr18-2-3-2015-basic-alarm-design | 可访问（含 shelving） |
| 规范 | ISA-TR18.2.5 监控与审计 | https://www.isa.org/products/isa-tr18-2-5-2022-alarm-system-monitoring-assessme | 可访问 |
| 规范 | ISA/IEC 62443 | https://www.isa.org/standards-and-publications/isa-standards/isa-iec-62443-series-of-standards | 可访问 |
| 规范 | ISA-95 | https://www.isa.org/standards-and-publications/isa-standards/isa-95-standard | 可访问，L0–L4 已核 |
| 参考 | Shelving 实现（QtALH） | https://ops.aps.anl.gov/manuals/QtALH/operate/shelving.html | 可访问，交互细节已核 |
| 参考 | 报警洪泛定义（Honeywell） | https://process.honeywell.com/content/dam/forge/en/documents/gated/honeywell-alarm-management-standards-whitepaper.pdf | PDF，按公开白皮书引用 |
| 参考 | 报警 KPI 批评（ProcessVue） | https://www.processvue.com/downloads/Alarm_system_performance_KPIs_V1_0.pdf | PDF，按公开资料引用 |
| 行业 | 南网变电运行管理标准·设备管理 | https://tech.bjx.com.cn/html/20071227/57964.shtml | 可访问，缺陷三级与时限已核 |
| 行业 | 变电站设备缺陷管理制度 | http://p.safehoo.com/Manage/System/Electric/201411/372376.shtml | 可访问，危急 24h 已核 |
| 参考 | FDA 21 CFR Part 11 | https://www.fda.gov/regulatory-information/search-fda-guidance-documents/part-11-electronic-records-electronic-signatures-scope-and-application | 官方页面 |

---

## 10. 边界与不确定（写清楚，比装作全知道强）

1. **厂商平台细节拿不到全貌。** 海康 8700 的模块清单来自 2014 年第三方评测页，现行版本可能有变化；申昊/亿嘉和/国自的**平台侧模块**（而非本体参数）公开材料很少，本文只对标了它们公开承认的能力。真要投标，必须拿技术协议/白皮书原文。
2. **西门子/施耐德不是巡检平台。** 它们是 DCS/SCADA，本文只对标「资产-维护-工单」「报表订阅」「报警归档」这些**模块级做法**，不代表它们有“巡检任务/到位率”概念。
3. **标准原文没读全。** ISA-18.2/62443/95 是付费标准，本文依据官方摘要页与公开技术报告（TR18.2.3/2.5）的描述；**具体条文号与强制措辞**在正式合规评审时要对照原文。
4. **KPI 目标值是行业通行值，不是合同值。** ≤6 条/h/人、洪泛 <1%、standing <10 来自行业实践与公开资料；最终以甲方运维考核表为准，写进合同前要确认。
5. **人日估算基于“熟悉本仓库的 1 名后端 + 0.5 名前端”**，含自测与文档，不含真机联调等待、不含甲方评审往返。
6. **本文不替代 `docs/reviews/industrial-gap.md`。** 那篇是代码级差距与排期，本篇是**对标依据与模块清单**；两份一起看，前者回答“怎么补”，后者回答“为什么这么补”。

---

### 附：与现有文档的关系

| 文档 | 作用 | 关系 |
|---|---|---|
| [`industrial-gap.md`](./industrial-gap.md) | 代码级差距、修复清单、排期 | 本篇是其**对标依据**；本篇 §8 的 10 项与它的 §4 清单可互相映射 |
| [`../open-source-references.md`](../open-source-references.md) | 开源项目选型与许可证 | 本篇 §1.2 补充了**用法**（抄什么/不抄什么） |
| [`../平台方案-定稿.md`](../平台方案-定稿.md) | 方案与容量 | 本篇 §6/§7 的台账字段与报表口径应回写进方案 |
| [`../验收清单-12月01.md`](../验收清单-12月01.md) | 验收项 | 本篇 §8 可直接转成“验收追问清单” |
