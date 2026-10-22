# 工业级对标与能力缺口评审

> 评审对象：`D:\Desktop\防爆机器人`（`server/app`、`web/src`、`deploy`、`docs`）
> 代码基线：`a34e695`（2026-10-22）
> 方法：读代码与部署文件；本机执行 `docker compose config`、`/health`、`/ready`、`/health/deep`；联网核对开源项目与规范
> 边界：**没有压测、没有真机、没有拿到客户合同/等保测评项**。文中容量数字是按代码路径推算，标注“推算”；不确定的写“不确定”
> 结论口径：
> - **缺**：没有，或只有占位；出事时没有兜底。
> - **弱**：有最小实现，但只覆盖单机/单厂商/演示规模；扩一档就露馅。
> - **够用**：满足一期合同与当前 1–2 台规模，现在不需要补。
>
> **评审期间工作区有并发改动（未提交）**：`deploy/docker-compose.tls.yml` 的服务名已从 `nginx` 改为 `jc-nginx`；`server/app/services/robot_runtime.py` 的轮询已从串行改为 `asyncio.gather` 四路并发。本文以“基线 + 工作区现状”为准，涉及处标注 **[已修/未提交]**。代码评审不应把“正在改”当成“已改好”，所以仍保留收口要求。

---

## 0. 先给结论

### 0.1 定性

这不是一套“工业级机器人平台”，而是一套**单站点的巡检上位机 + 告警/工单闭环**：

- 在 ISA-95 分层里，它是 **L3 作业层**，不是 L1/L2 控制层。它不控车、不做安全回路、不做 SLAM。
- 它把“设备接入、告警、工单、视频、报表、权限、审计”做成了一个单体应用。单站点 1–2 台机器人，这个选择是**对的**；但每一层的工业能力都没有做深。
- 真正的工业栈是分层的：连接层（PLC4X/EMQX）、平台层（ThingsBoard）、历史层（TimescaleDB/InfluxDB）、可视化层（Grafana/FUXA）、存储层（MinIO/NVR）、运维层（Prometheus/Loki）。我们把这些**全塞进了一个 FastAPI 进程**。

### 0.2 五条最硬的差距

1. **状态同步是“轮询 + 进程内缓存”，没有设备影子/事件流。** 1s 是名义值；基线每轮串行 4 个 HTTP（4×RTT），工作区已改四路并发、失败保留旧值、`fresh` 标记和真实 `age_s` **[已修/未提交]**；仍缺字段级新鲜度与“部分数据过期”的 UI。进程重启即失忆，残留任务一律标 failed（`main.py:71-83`）。
2. **平台自己挂了没人知道。** 有 `/health`、`/ready`、`/health/deep`、loop lag，但没有 `/metrics`、没有 Prometheus/Grafana、没有平台自身告警；Docker 日志上限合计约 230MB，撑不过几天。
3. **没有真正的灾备。** 单机、单 MySQL、每日 `mysqldump` 到本地、保留 14 天、不加密、无异地、无 PITR；恢复演练只在本机 SQLite 做过，生产 MySQL 未演练。
4. **协议层是厂商私有 HTTP。** Modbus 只有 50 行、功能码 03/04、每个寄存器新建一次 TCP；MQTT 是 QoS 0、无 TLS、无 LWT；没有 OPC UA/Sparkplug/GB28181/ONVIF。换一家设备就要重写接入层。
5. **告警只做到“去重 + 升级”，录像只有 2 路且 go2rtc 是宿主单点。** 没有 ISA-18.2 的报警分级/搁置/泛滥抑制/KPI；没有事件录像证据包；go2rtc 不在 compose 里、没有 healthcheck。

### 0.3 12 月验收前的判断

**不要补“工业级”，要补“可演示、可恢复、可追溯”。**

- 现在做 HA、时序库、VDA5050、GB28181、3D，都是负 ROI：真机还没到，做完也无法验证，还会挤占联调时间。
- 现在做 **TLS 修复、采集并行、/metrics、日志留存、异地备份、录像看护、保留策略、坐标标定、下发幂等、验收证据导出**，是正 ROI：每一项都能在验收现场被看见、被演示、被追责。
- 一句话：**12 月前把“单机可靠性”做扎实，二期再谈“工业级横向能力”。**

### 0.4 工作区当前状态（截至 2026-10-22 23:40，未提交）

评审期间发现的 4 个问题，工作区已改（**未提交、未回归**）：

| 项 | 评审开始时 | 工作区现在 | 仍需 |
|---|---|---|---|
| 轮询并行 | 基线四路串行，慢网会假离线 | 四路 `gather`；失败保留旧值；`fresh` 标记；`age_s` 用真实值 | 字段级 `fetched_at`；UI 显示“部分数据过期”；半坏网络回归 |
| `galileo` NameError | `_check_clock(..., galileo)` 未定义，`evaluate()` 永远执行不到 → **告警静默** | 已补 `galileo = merged["galileo"]`，`age_s` 改真实值 | 把 `evaluate()` 放在 `_check_clock` 之前或单独 try，避免时钟检查异常再次吞掉告警 |
| 报表缓存 500 | `_summary_out` 未定义，`/reports/summary` 必 500 | 已抽 `_summary_impl`，`out` 缓存 15s | 缓存 key 目前只有日期；加筛选维度时要带上，否则串数据 |
| 环境读数保留 | 只增不删 | 已加 `sensor.keep_days=90` 清理 | 单条 `DELETE` 删 1,550 万行会锁表，改分批/分区 |

这四项说明工作区是活的；本文其余判断基于基线 `a34e695`，仍然成立。**已修项在跑完 `pytest` + 断网/半坏网络回归之前，不要在验收材料里写“已解决”。**

---

## 1. 我们站在工业栈的哪一层

| 层级 | 典型系统 | 我们的对应物 | 结论 |
|---|---|---|---|
| L4 业务/ERP | SAP、用友、MES | 无 | 合同外 |
| L3 作业/巡检 | 巡检平台、EHS、工单系统 | **本平台**（任务、告警、工单、报表） | 主战场，但只做了“单站点闭环” |
| L2 监控/SCADA | FUXA、OpenSCADA、Ignition | Vue 驾驶舱 + 自绘地图 | 有 HMI 壳，没有 tag/历史/报警治理 |
| L1 控制/导航 | JCROB 本体、ROS 2 Nav2 | 厂商本体，平台只下发点位 | 不做，正确 |
| L0.5 连接 | PLC4X、EMQX、Node-RED | JCROB Adapter + 50 行 Modbus + paho | 最薄的一层 |
| L0 现场设备 | PLC、气体报警器、温湿度 | Modbus TCP / MQTT 网关 | 只覆盖“能读一个寄存器” |
| 横向：数据/运维 | ThingsBoard、Prometheus、MinIO、NVR | 自建表 + 本地磁盘 | 没有独立的历史/对象/监控层 |

**一句话**：我们相当于 ThingsBoard 的设备台账与告警（约 20%）+ FUXA 的 HMI（约 20%）+ 一个工单系统 + 一个私有协议适配器；没有它们的接入层、规则引擎、历史库、运维面。

这也解释了为什么“加一个功能”很快、“加一个设备/加一个厂区”很慢：**功能是竖着写的，接入是横着长的。**

---

## 2. 对标项目：它们解决什么，我们缺哪块

### 2.1 总表

| 项目 | 解决什么问题 | 我们的对应物 | 缺的那块 | 结论 |
|---|---|---|---|---|
| [Open-RMF](https://github.com/open-rmf/rmf) | 多机器人车队：任务派发、交通管制、门/电梯/充电桩资源协调 | 多设备轮询 + 平台逐点巡航 | 车队队列、交通冲突、资源锁、异构车队适配 | 二期，>3 台或客户要车队时 |
| [VDA5050](https://github.com/VDA5050/VDA5050) | AGV/AMR 的订单/状态/即时指令标准（MQTT） | 只抄了状态枚举（`task_dispatch.py:25-32`） | Order 图、orderUpdateId、InstantActions、Errors、连接心跳 | 借消息模型，不声称合规 |
| [Apache PLC4X](https://github.com/apache/plc4x) | 一套 API 接多种工业协议（S7/Modbus/OPC UA/EtherNet-IP…） | 50 行 Modbus TCP 03/04 | OPC UA、RTU、字节序、批量读、连接池、订阅 | 二期，有 OPC UA 需求时 |
| [ThingsBoard](https://github.com/thingsboard/thingsboard) | 设备/资产模型、遥测、规则引擎、告警生命周期、仪表盘 | 设备表 + 自定义 AlarmStore + Vue 页 | 设备 profile、资产关系、规则链、告警配置化 | 借产品抽象，不搬微服务 |
| [EMQX](https://github.com/emqx/emqx) | 大规模 MQTT Broker：集群、ACL、桥接、共享订阅 | paho 客户端直连客户 Broker | 自有 Broker、QoS1/2、retained、LWT、主题 ACL | 二期，多厂商/边缘时 |
| [Prometheus](https://github.com/prometheus/prometheus) / [Grafana](https://github.com/grafana/grafana) | 指标采集、PromQL、告警规则、仪表盘 | `/health/deep` JSON + loop lag | `/metrics`、指标命名、告警规则、看板 | **12 月前最小集** |
| [Node-RED](https://github.com/node-red/node-red) | 低代码流程编排、协议节点、Webhook 胶水 | 硬编码的 notify/规则 | 可视化规则/现场自定义集成 | 可选，只做非安全胶水 |
| [OpenSCADA](https://oscada.org/) / [FUXA](https://github.com/frangoteam/FUXA) | SCADA/HMI：tag、驱动、历史、报警、画面 | 自绘 Vue HMI | tag 模型、历史库、报警分级、面板复用 | 借模型，不套壳 |
| [ROS 2 Nav2](https://github.com/ros-navigation/navigation2) | 导航栈：行为树、规划、控制、代价地图、恢复 | 厂商导航，平台只显示位姿 | 导航健康诊断、路径预览、恢复状态 | 借诊断模型，不跑 Nav2 |
| [MinIO](https://github.com/minio/minio) | S3 对象存储：生命周期、版本、预签名、对象锁 | 本地磁盘目录 | 对象 API、生命周期、校验、不可变证据 | 二期；注意社区版维护模式 |
| [ZLMediaKit](https://github.com/ZLMediaKit/ZLMediaKit) / [wvp-GB28181-pro](https://github.com/648540858/wvp-GB28181-pro) / [MediaMTX](https://github.com/bluenviron/mediamtx) | GB28181/RTSP/WebRTC 接入、转码、录像、国标级联 | go2rtc + ffmpeg 分段，最多 2 路 | GB28181 信令/级联、ONVIF、多路、硬件转码、流健康 | 二期；单厂 2 路不必上 |

### 2.2 逐项说明

#### 2.2.1 Open-RMF

- **它解决什么**：多机器人车队的任务派发、交通冲突消解、门/电梯/充电桩等资源协调，以及“不同厂商的车”通过 fleet adapter 接入同一套调度。核心不是“地图”，是**任务队列 + 资源锁 + 冲突解决**。
- **我们有什么**：每台设备一个轮询任务（`services/robot_runtime.py`）；平台逐点下发 + 3s 查状态（`services/cruise.py`）；一台车同时只允许一个任务（`task_dispatch.py` preflight）。
- **缺什么**：
  - 任务队列/优先级/抢占：现在是“点一下跑一条”，没有排队、没有优先级、没有失败重派。
  - 交通与资源：没有“同一段路/同一电梯/同一充电桩”的互斥；多车会各走各的。
  - 异构适配：`adapters/registry.py` 有注册表，但只有 jcrob/deeprobotics 两家，能力探测还是“能读什么”而不是“能执行什么”。
  - 充电调度：只有低电告警，没有“任务排期避开低电/自动回充排队”。
- **怎么用**：借它的 **fleet adapter 接口**和 **task state 模型**；不引入 ROS 2 运行时。只有 >3 台或客户明确要“车队”时才值得做，二期。

#### 2.2.2 VDA5050

- **它解决什么**：把 AGV/AMR 的“订单（Order）—状态（State）—即时指令（InstantActions）”标准化，走 MQTT；订单是**节点/边组成的图**，带 `orderId`、`orderUpdateId`，支持增量更新、动作阻塞类型、错误数组、连接心跳。
- **我们有什么**：`task_dispatch.py:25-32` 只做了状态名映射（INITIALIZING/RUNNING/PAUSED/FINISHED/FAILED）；`_order_payload()` 自己拼了一个 `orderId=JC-时间戳`、`orderUpdateId=0` 的私有 JSON。
- **缺什么**：
  - Order 图与增量更新：没有 node/edge、没有 updateId 语义，无法“改单不重发”。
  - InstantActions：急停/暂停/继续/取消没有标准化动作模型。
  - Errors/Information：机器人错误码没有结构化数组，只有字符串。
  - 连接契约：没有 heartbeat、没有 `connection` 主题、没有 retained state。
  - 一致性测试：没有 conformance 用例，不能对外说“支持 VDA5050”。
- **怎么用**：把它当**消息设计参考**，不是合规目标。近期最值得抄的是：`orderId + orderUpdateId + actionId` 的幂等三元组、动作状态机、错误数组。二期若客户有多厂商车队，再评估真的接 VDA5050。

#### 2.2.3 Apache PLC4X

- **它解决什么**：用统一 API 访问 S7、Modbus、OPC UA、EtherNet/IP、BACnet 等 PLC 协议；支持连接串、批量读写、订阅、数据类型映射。工业现场“协议比设备多”的现实解。
- **我们有什么**：`services/sensor_gateway.py` 里 50 行 Modbus TCP，功能码 03/04，每个寄存器 `socket.create_connection` 新建连接；MQTT 用 paho。
- **缺什么**：
  - OPC UA：完全没有。工厂 DCS/PLC 的主流接口是 OPC UA，不是 Modbus。
  - Modbus RTU/串口：没有；现场气体报警器很多是 RS485。
  - 字节序/字序/32 位拼接：`scale()` 只做乘加，没有 endianness/word order。
  - 连接与批量：一寄存器一连接，10 个测点 10 次握手；没有批量读、没有断线重连会话。
  - 安全：没有 OPC UA 证书/签名/加密策略。
- **怎么用**：如果二期要接 DCS/PLC，**不要自己写 OPC UA 客户端**，用 PLC4X（JVM sidecar）或 Python `asyncua`；Modbus 至少改成“长连接 + 批量读 + 字节序配置”。单厂 1–2 个 Modbus 表，现在这 50 行够用，但要在文档里写清边界。

#### 2.2.4 ThingsBoard

- **它解决什么**：设备/资产模型、设备 profile、遥测存储、规则引擎、告警生命周期、仪表盘、多租户、RPC。工业 IoT 平台的产品抽象基本都绕不开它。
- **我们有什么**：`robot`、`sensor`、`sensor_gateway`、`alarm_record`、`work_order`、`telemetry_sample` 这些表；自定义 `AlarmStore`；Vue 页面。
- **缺什么**：
  - 设备 profile：接入参数、传输类型、编解码、告警规则现在散在 `settings`、`robot`、`sensor` 三处，换型号要改代码。
  - 资产/关系：没有“厂区—车间—设备—点位”的层级；报表只能按 robot_id 分组。
  - 规则引擎：告警规则是 Python 里的 if，不是配置；客户想加“连续 3 次超限且温度同时 >X”就要改代码。
  - 告警生命周期：有确认/处置/关闭/升级，但没有“搁置（shelving）”“按设备状态抑制”“首出（first-out）”。
  - 遥测保留策略：见 §3.5，设计有、代码没有。
- **怎么用**：借 **device profile + asset relation + alarm lifecycle** 三个抽象；不要搬它的微服务和消息队列。我们 4 周 MVP 经不起那个复杂度。

#### 2.2.5 EMQX

- **它解决什么**：大规模 MQTT 接入（集群、共享订阅、ACL、JWT/mTLS 认证、规则引擎、桥接、retained/LWT）。设备侧“主动上报、平台订阅”的标准做法。
- **我们有什么**：`sensor_gateway.py` 用 paho `MQTTv311`，`qos=0`，无 TLS、无 LWT、无 retained，`on_message` 里同步写库。
- **缺什么**：
  - 没有自己的 Broker：现场要么给客户一个 Broker 地址，要么直连设备；没有主题命名空间、没有 ACL。
  - QoS 0：断线期间的读数直接丢，没有补传。
  - 没有 LWT/retained：设备离线状态要靠平台超时猜。
  - `on_message` 同步 `commit`：paho 网络线程被 DB 阻塞，压测下会丢消息。
- **怎么用**：单厂 1 台机器人 + 几个传感器，**不需要 EMQX**；如果二期有“多厂商设备 + 边缘网关 + 云端”，再上 EMQX 或 Mosquitto。现在最该做的是把 MQTT 的 **QoS1 + LWT + 主题规范 + 异步入库** 补齐，约 2 人日。

#### 2.2.6 Prometheus / Grafana

- **它解决什么**：指标采集（pull）、时序存储、PromQL、告警规则、Alertmanager、看板。工业运维的“仪表盘”事实标准。
- **我们有什么**：`/health`（存活）、`/ready`（查库）、`/health/deep`（链路/循环/loop lag/磁盘），`LoopLagMonitor` 已经在算事件循环延迟（`tasks/runner.py`）。
- **缺什么**：
  - 没有 `/metrics`：所有指标只存在于 JSON 里，Prometheus 抓不到。
  - 没有告警规则：平台挂了、库挂了、轮询停了、录像停了、磁盘满了，都只能等人发现。
  - 没有看板：现场运维没有一个“今天系统健康吗”的页面。
  - 没有历史：`/health/deep` 只有当下值，排障时无法回看“昨晚 2 点 loop lag 是否飙过”。
- **怎么用**：**这是 12 月前性价比最高的一项**。用 `prometheus-client` 暴露 8–10 个指标，加一个 `monitoring` compose profile（Prometheus + Grafana + node_exporter + mysqld-exporter），3 人日以内；不需要改业务架构。

#### 2.2.7 Node-RED

- **它解决什么**：低代码流程编排，把 HTTP/MQTT/Modbus/邮件/数据库节点连起来，适合现场“客户想加一个通知/转发/看板”的胶水需求。
- **我们有什么**：硬编码的 `services/notify.py`、`services/alarms.py`、`settings_schema.py`。好处是可测试、可审计；坏处是每个现场定制都要改代码发版。
- **缺什么**：没有“客户可配置的规则/流程”。但这不是当前瓶颈。
- **怎么用**：**不建议嵌进主链路**。安全相关（急停、下发、联锁）绝不能放 Node-RED；非安全胶水（比如“某告警同时写一份到客户 MES”）可以用它做旁路。我们现在的通知重试/HMAC 已经够用，Node-RED 二期再看。

#### 2.2.8 OpenSCADA / FUXA

- **它解决什么**：SCADA/HMI 的成熟模型：tag（点位）定义、工程单位、量程、死区、驱动、历史归档、报警分级、画面/面板复用。FUXA 是 Web 版，MIT；OpenSCADA 是老牌 GPL 项目。
- **我们有什么**：自绘 Canvas 地图、Vue 页面、`sensor` 表带 `warn_high/crit_high` 阈值、`PointDraft` 点位。
- **缺什么**：
  - tag 模型：没有“工程单位/量程/死区/采集周期/归档方式”的统一元数据；传感器和机器人状态是两套。
  - 历史归档：没有 1 分钟聚合、没有降采样存储、没有归档策略。
  - 报警治理：只有阈值比较，没有死区/延时/搁置/首出/泛滥抑制。
  - 画面复用：每个页面手写，没有 faceplate/组件库。
- **怎么用**：借 **tag 元数据 + 报警状态机 + 历史归档** 三个模型；不要套 SCADA 整壳（它的驱动/画面体系和我们不匹配）。近期只做“报警死区/延时 + 聚合历史”，见 §4。

#### 2.2.9 ROS 2 Nav2

- **它解决什么**：ROS 2 的导航栈：行为树（BT Navigator）、全局/局部规划、控制器、代价地图、恢复行为、定位。机器人“怎么走”的事实标准。
- **我们有什么**：厂商自带导航；平台只读位姿、下发点位、3s 查 `get_order()` 状态；到达判定“FINISHED + 1.5m 半径”（`cruise.py`）。
- **缺什么**：
  - 导航健康：看不到“代价地图是否被堵”“是否在恢复行为”“定位置信度多少”；只能看到最终失败。
  - 路径预览：下发前不能显示“车准备怎么走”，现场不敢点。
  - 恢复策略：车卡住后平台只会超时失败，没有“重试/换点/呼叫人工”的编排。
- **怎么用**：借 **diagnostics/状态机** 的表达方式，不跑 Nav2。近期最值得做的是“下发前路径/目标点预览 + 失败原因分类”，让操作员敢用。

#### 2.2.10 MinIO

- **它解决什么**：S3 兼容对象存储：bucket、生命周期、版本、预签名 URL、对象锁（WORM）、纠删码。适合存录像、导出、备份、AI 原图。
- **我们有什么**：`/data/jcrob-platform/recordings`、`maps`、`uploads` 本地目录；DB 里存路径；没有校验和、没有对象锁。
- **缺什么**：
  - 对象 API：外部系统拿录像只能走平台接口，不能直连 S3。
  - 生命周期：录像按文件 mtime 删，没有 bucket lifecycle/归档。
  - 不可变：审计证据/事件录像可以被有文件权限的人删改。
  - 容量：单盘，没有纠删/副本。
- **怎么用**：**单机 2 路录像不需要 MinIO**。但要注意：MinIO 社区版在 2025 年底进入维护模式（[InfoQ 报道](https://www.infoq.com/news/2025/12/minio-s3-api-alternatives/)），新项目不建议把它当长期基础设施；如果二期要对象存储，评估 [Garage](https://github.com/deuxfleurs-org/garage) / [SeaweedFS](https://github.com/seaweedfs/seaweedfs) / Ceph。近期只做“录像文件 sha256 + 事件清单 + 异地副本”，比上对象存储更划算。

#### 2.2.11 NVR / GB28181（ZLMediaKit / wvp-pro / MediaMTX）

- **它解决什么**：RTSP/RTMP/GB28181 接入、转封装、WebRTC/FLV 播放、录像、国标级联、ONVIF 发现。工厂视频的“标准入口”。
- **我们有什么**：go2rtc（宿主进程，不在 compose）+ nginx 反代 `/go2rtc/` + ffmpeg 分段落盘，最多 2 路（`recorder.py:34`）。
- **缺什么**：
  - GB28181：没有信令、没有设备目录、没有级联；客户若已有国标平台，我们接不进去。
  - ONVIF：没有自动发现/云台控制；相机要手工填 RTSP。
  - 多路与转码：2 路上限，纯 CPU；没有硬件转码。
  - 流健康：没有“最后一帧时间/码率/卡顿”指标；go2rtc 挂了只能看黑屏。
  - NVR 存储：没有循环覆盖、没有索引、没有按事件检索。
- **怎么用**：单厂 2 路，**MediaMTX 是比 go2rtc 更稳的替代**（单二进制、MIT、RTSP→WebRTC）；如果客户明确要 GB28181 级联，再上 ZLMediaKit + wvp-pro。近期先做“go2rtc 守护 + 最后一帧检测 + 事件片段”，不要上 NVR。

### 2.3 还值得看的项目（不逐一展开）

| 项目 | 用途 | 我们对应的缺口 | 建议 |
|---|---|---|---|
| [Keycloak](https://github.com/keycloak/keycloak) | OIDC/SAML/LDAP/SSO | 本地账号，无 SSO/LDAP | 二期，客户有 AD 时 |
| [OpenTelemetry](https://opentelemetry.io/) | 分布式追踪/指标/日志统一 | 无 trace、无 request id | 二期，多服务时 |
| [Grafana Loki](https://github.com/grafana/loki) | 日志聚合 | 只有 Docker json-file | 二期；一期先文件轮转 |
| [VictoriaMetrics](https://github.com/VictoriaMetrics/VictoriaMetrics) / [TimescaleDB](https://github.com/timescale/timescaledb) | 时序库/聚合 | MySQL 存遥测，无聚合 | 二期，>10 台或要 180 天 |
| [MySQL InnoDB Cluster](https://dev.mysql.com/doc/refman/8.4/en/mysql-innodb-cluster-introduction.html) | MySQL 高可用 | 单实例 | 二期，客户要求 RTO<15min 时 |
| [restic](https://github.com/restic/restic) | 加密增量备份 | mysqldump 本地 14 天 | **12 月前可先用 age+rsync** |
| [Eclipse Mosquitto](https://github.com/eclipse-mosquitto/mosquitto) | 轻量 MQTT Broker | 无自有 Broker | 二期边缘，比 EMQX 轻 |
| [Sparkplug B](https://sparkplug.eclipse.org/) | MQTT 工业数据规范（状态/别名/历史） | MQTT 自定义 JSON | 二期，多厂商时 |
| [OPC UA](https://opcfoundation.org/about/opc-technologies/opc-ua/) | 工业互操作标准 | 无 | 二期，接 DCS/PLC 时 |
| [ISA-18.2](https://webstore.ansi.org/standards/isa/ANSIISA182016) | 报警管理标准 | 有去重/升级，无分级/搁置/KPI | 一期后补 KPI，二期补治理 |
| [IEC 62443](https://www.isa.org/standards-and-publications/isa-standards/isa-iec-62443-series-of-standards) | 工业网络安全分区/管道 | 单机内网，无分区 | 二期，客户做等保/工控安全时 |

---

## 3. 八维对比：工业级做法 vs 我们现状

### 3.0 总表

| 维度 | 差距等级 | 一句话理由 |
|---|---|---|
| 并发 | **弱**（1–2 台够用，10 台以上缺） | 单进程 + 近 10 个常驻线程/任务 + 每设备 4 请求（工作区已并行）；无队列/背压/隔离 |
| 延迟 | **弱** | 基线 4×RTT（最坏 12s）；工作区并行后≈1×RTT；UI 靠 1s 轮询；无事件推送 |
| 状态同步 | **缺** | 进程内缓存、无设备影子、无幂等、重启即失忆 |
| 权限 | **够用**（单站点）/ **弱**（多系统） | 7 角色 + TOTP + API Key 够用；无 SSO/mTLS/ABAC，admin 仍是超级用户 |
| 数据保留 | **弱** | 录像够用；日志/环境读数/审计归档缺，设计与实现不一致 |
| 可观测性 | **缺** | 有探针，无 metrics/告警/集中日志/trace |
| 部署与灾备 | **弱**（单机可接受）/ **缺**（DR） | 单机单库、本地备份、无异地/PITR；TLS 覆盖文件本身是坏的 |
| 协议标准化 | **缺**（多厂商）/ **够用**（单厂商） | 私有 HTTP + 50 行 Modbus；无 OPC UA/Sparkplug/GB28181 |

### 3.1 并发

| 对比项 | 工业级做法 | 我们现状 | 等级 |
|---|---|---|---|
| API 进程 | 无状态 API 多副本 + 负载均衡；后台任务独立 worker | `uvicorn --workers 1`；`main.py` 里同时起轮询、遥测、录像 janitor、计划调度、磁盘监控、看门狗、工单升级、传感器网关、巡航线程 | 弱 |
| 设备接入 | 每设备独立会话/actor，连接池，失败隔离 | 每设备一个 asyncio 任务；基线一轮内 `get_status → get_info → get_galileo → get_pose` 串行（`poller.py:29-32`），工作区已改 `gather` **[已修/未提交]**；失败隔离仍未做 | 弱 |
| 写路径 | 命令队列 + 幂等 + 限流 + 熔断 | 同步端点直接调适配器；`asyncio.run()` 在同步函数里跑协程（`task_dispatch.py:_call`） | 弱 |
| 背压 | 队列长度/丢弃策略/死信 | 通知队列 `maxsize=500`，满了丢告警（`notify.py:154`）；轮询无背压 | 弱 |
| 视频 | 独立媒体服务、硬件转码、多路 | 2 路 ffmpeg（`recorder.py:34`），CPU 转码，go2rtc 在宿主 | 弱 |
| 报表 | 预聚合/异步导出/分页 | `reports.py` 把区间内告警、读数、遥测全部 `.all()` 进内存；工作区加了 15s 缓存 **[已修/未提交]**，但仍是全量扫描，且缓存 key 只有日期 | 弱（已修/未回归） |
| 限流 | 按用户/租户/接口分级 | nginx 20r/s（按 API Key 或 IP），无按用户写操作限流 | 弱 |

**判断**：1–2 台机器人、单站点，当前并发模型**够用**；到 10 台，轮询请求数 40 req/s、线程/协程竞争、报表全量加载会先出问题；到 50 台是**缺**。

### 3.2 延迟

| 对比项 | 工业级做法 | 我们现状 | 等级 |
|---|---|---|---|
| 机器人状态 | 设备主动上报（MQTT 1–10Hz），平台订阅 | 1s 定时轮询；基线每轮 4 个串行 HTTP，工作区已改 `gather` 四路并发 **[已修/未提交]**；单请求读超时 3s（`config.py:76`） | 弱 |
| 部分失败语义 | 每路独立新鲜度，失败保留旧值并标“部分过期” | 工作区已保留旧值 + `fresh` 标记、`age_s` 用真实值 **[已修/未提交]**；仍无字段级 `fetched_at`，UI 不区分“哪一路过期” | 弱（已修/未回归） |
| 实际新鲜度 | p95 < 1s | 基线 4×RTT；100ms RTT 约 0.4s，500ms RTT 约 2s，最坏 12s；工作区并行后≈1×RTT；UI 再 1s 轮询（`stores/robot.ts:4`） | 弱 |
| 告警产生 | 边缘/流式判定，亚秒级 | 轮询成功后同步判定；离线 10s 才报，critical 30s（`alarms.py`） | 弱 |
| 任务对账 | 事件驱动 + 心跳 | 巡航 3s 查一次（`cruise.py:POLL_S`）；全局看门狗 15s（`TaskWatchdog`） | 弱 |
| 视频 | WebRTC < 500ms | go2rtc MSE 约 0.5–1s；MJPEG 转码更慢 | 够用 |
| 时间基准 | NTP/PTP + 偏差告警 | `clock.max_skew_s` 有设置、`robot_runtime.py:161` 有比较；未强制 NTP，未做时间源监控 | 弱 |

**关键 failure mode（基线）**：四个请求串行，任一慢就把整轮拖长；而 `StateCache.online` 是 `age_s <= 5.0`（`state_cache.py`）。如果一轮超过 5s，页面会先显示离线，10s 后触发离线告警——**慢网络会被误判成机器人失联**。工作区已改成“四路并发 + 失败保留旧值 + `fresh` 标记 + 真实 `age_s`”，主因消除；剩余问题是“哪一路过期”不可见、告警 `evaluate` 仍排在 `_check_clock` 之后（时钟检查异常会再次吞掉告警）。收口要求见 §4 第 2 项。

**公平地说**：8.40 的 mock 演练里 `age_s` 中位数是 0.86s（`docs/联调演练报告-8.40.md`），局域网 + 模拟器下完全够用。风险在“真机跨网段 + 现场 WiFi 抖动 + 机器人 HTTP 偶发慢”，不是现在就跑不动。

### 3.3 状态同步

| 对比项 | 工业级做法 | 我们现状 | 等级 |
|---|---|---|---|
| 真相源 | 设备影子/数字孪生（desired/reported，带版本） | 进程内 `StateCache`，只存 reported；无 desired、无版本 | 缺 |
| 命令幂等 | `orderId + orderUpdateId + actionId` 唯一 | `orderId=JC-时间戳`、`orderUpdateId=0`；`TaskRun` 没有 dispatch 侧幂等键 | 缺 |
| 重启恢复 | 重连后与设备对账，接管仍在执行的任务 | 启动时把 `running/dispatched` 一律标 `failed`（`main.py:71-83`） | 弱 |
| 事件流 | MQTT/WS/SSE 推送；retained 状态 | 前端 1s 轮询 `/status`；后端无 WS 端点（nginx 配了 `/ws/`，代码里没有 `@router.websocket`） | 缺 |
| 多实例 | 共享状态（Redis/DB/消息总线） | 状态在进程内，只能单实例 | 缺（当前单机可接受） |
| 断网续传 | 边缘缓存 + 序列号 + 补传 | 无；传感器 MQTT QoS 0、Modbus 失败即丢 | 缺 |
| 时钟/顺序 | 单调时钟 + 序列号 + 幂等去重 | 用 `time.monotonic()` 算新鲜度（好），但消息无序列号 | 弱 |

**判断**：单机单实例，当前“缓存 + 轮询”能跑；但它把“实时性、重启恢复、幂等”三件事都压给了调用方。真机联调时只要出现一次“重启后任务卡 running/重复下发”，就会变成验收事故。

### 3.4 权限

| 对比项 | 工业级做法 | 我们现状 | 等级 |
|---|---|---|---|
| 身份 | SSO/OIDC/LDAP/SAML；服务间 mTLS | 本地账号 + TOTP；API Key（SHA-256 存储、4 个 scope、可过期） | 够用（单站点） |
| 授权 | RBAC/ABAC + 策略引擎 + 对象级 | 7 角色 + 端点 `require_roles`（`deps.py:64`）；无对象级/行级 | 够用 |
| 三权分立 | 系统/安全/审计互斥，无双全账号 | 有 `sysadmin/secadmin/auditor`，但保留 `admin` 超级角色且大量端点 `require_roles("admin", ...)` | 弱 |
| 会话 | 短 TTL、吊销、设备管理 | JWT + `token_version` 吊销；改密/登出失效；无会话列表 | 够用 |
| 机器身份 | mTLS/短期令牌/密钥轮换 | API Key 哈希存储、过期校验（`api_auth.py:24`）；无自动轮换 | 够用 |
| 审计 | 独立 WORM/远程 syslog/每日锚定 | 哈希链在同库；迁移 `0017_rechain_audit.py` 曾整表重算哈希 | 弱 |
| 最小权限 | 按操作/对象/环境 | 角色粗粒度；`admin` 可改一切；无审批流 | 弱 |

**判断**：对“内网单站点 + 7 个角色 + 等保最小集”，这套**够用**；对“多系统/多厂区/工控安全分区”，**弱**。最值得补的不是再加角色，而是：**去掉 `admin` 的日常使用、关键操作双人复核、审计链外锚定**。

### 3.5 数据保留

| 对比项 | 工业级做法 | 我们现状 | 等级 |
|---|---|---|---|
| 遥测 | 1s 原始 7 天 + 1min 聚合 180 天 + 按天分区/`DROP PARTITION` | 10s 采样、7 天、`DELETE`（`telemetry.py:30-31,101`）；无聚合、无分区 | 弱 |
| 环境读数 | 5s 降采样、90 天、分区/批量清理 | 工作区已加 `sensor.keep_days=90` 清理 **[已修/未提交]**；仍是一条 `DELETE`、无分区，首次删约 1,550 万行会锁表；历史查询仍全量加载 | 弱（收口中） |
| 告警/工单 | 长期保留 + 归档 + 法务留存 | 长期保留，无归档；表会一直长 | 够用（当前量小） |
| 审计 | 180 天~6 个月，WORM/异地 | 永久保留，哈希链，无归档/外锚 | 弱 |
| 平台日志 | 集中日志 180 天+ | stdout → Docker json-file，合计约 230MB；`/app/logs` 挂了卷但代码不写文件 | 缺 |
| 录像 | 30 天/容量上限/事件保留/对象锁 | 30 天/800GB/低于 5GB 停录（`recorder.py:181+`）；无事件保留/对象锁 | 够用 |
| 备份 | 3-2-1、加密、异地、定期恢复 | 每日 `mysqldump` 到本地，保留 14 天，不加密，无异地（`backup.sh:14`） | 缺 |
| 证据保全 | 法律保留/不可变存储 | 文件可被有权限的人删改；审计可被 DBA 重算 | 缺 |

**两个具体矛盾**：

1. 设计文档写“1s 原始 7 天 + 1 分钟聚合 180 天，按天 RANGE 分区，`DROP PARTITION`”（`docs/平台方案-定稿.md` §12），代码是“10s 采样 + 7 天 + `DELETE`”。这不是优化问题，是**设计承诺没落地**。
2. 录像“30 天 / 800GB”在 2 路 2Mbps 下算不平：2×2Mbps ≈ 43.2GB/天，800GB 只能存约 **18.5 天**（推算；实际码率未测）。要么降码率/事件录像，要么把保留天数写成“容量优先”。

### 3.6 可观测性

| 对比项 | 工业级做法 | 我们现状 | 等级 |
|---|---|---|---|
| 指标 | Prometheus 指标 + RED/USE + SLO | 无 `/metrics`；只有 JSON 探针 | 缺 |
| 日志 | 结构化 + 集中采集 + 180 天 | stdout 文本；Docker 100MB/30MB 上限；无 request id | 缺 |
| 追踪 | OpenTelemetry trace/span | 无 | 缺 |
| 告警 | Alertmanager/规则/分级/静默 | 无平台自身告警；只有业务告警外发 | 缺 |
| 健康检查 | 存活/就绪/深探针 | `/health`、`/ready`、`/health/deep`、loop lag、服务重启计数 | 够用 |
| 业务 KPI | 告警率/确认时长/在线率/录像可用率 | 报表有告警统计、确认/处置时长、在线率；无告警泛滥 KPI | 弱 |
| 合成探测 | 外部拨测/黑盒 | 无；靠人打开页面 | 缺 |

**判断**：这是**投入最小、收益最大**的一维。现有 `health_deep` 已经把数据准备好了，只差一个 `/metrics` 和几条告警规则。

### 3.7 部署与灾备

| 对比项 | 工业级做法 | 我们现状 | 等级 |
|---|---|---|---|
| 拓扑 | 双机/集群/边缘+中心 | 单机 3 容器 + 宿主 go2rtc；`restart: unless-stopped` | 弱（单站点可接受） |
| 数据库 | 主从/组复制 + binlog PITR | 单 MySQL 8.4；每日全量 dump；无 PITR 工具/演练 | 缺 |
| 备份 | 加密、异地、不可变、定期恢复 | 本地 14 天、明文、无校验、无异地；恢复演练只在本机 SQLite 做过 | 缺 |
| RPO/RTO | 明确到分钟，写进合同/ runbook | 未定义；按每日 2 点备份推算 RPO≈24h、RTO≈30–60min（手工） | 缺 |
| 发布 | 镜像 digest 固定、可回滚、灰度 | 本地 build tag（`jc-server:0.2.0`），无 registry/digest，回滚靠重新 build | 弱 |
| 配置/密钥 | Vault/KMS/密封 | `deploy/env` 明文；备份里也打包 env（`backup.sh`） | 弱 |
| TLS | 默认开启、证书轮换 | 服务名已改为 `jc-nginx` **[已修/未提交]**，`docker compose config` 可过；但 `tls.conf` 仍缺 `limit_req`、访问日志脱敏、`/ws/`、MJPEG 不缓冲、静态缓存 | 弱 |
| 生产开关 | 默认关文档/调试/默认口令 | `docs_enabled` 默认 True（`config.py:40`），`deploy/env.example` 没设 `JC_DOCS_ENABLED=false`；`assert_production_safe()` 只查 JWT 密钥和初始口令，不查 DB 口令、不查 docs | 弱 |
| 主机 | UPS、NTP、磁盘/温度监控 | 无 UPS/NTP 要求；只有应用内磁盘监控 | 缺 |
| 迁移 | 备份后迁移、expand/contract、可回滚 | 容器启动直接 `alembic upgrade head`，失败退出；无迁移前备份 | 弱 |

**评审开始时实测的部署缺陷（服务名已由并发改动修复，其余仍在）**：

```text
# 评审开始时（基线 a34e695）
$ docker compose -f docker-compose.yml -f docker-compose.tls.yml config --services
service "nginx" has neither an image nor a build context specified: invalid compose project

# 工作区当前（服务名已改 jc-nginx）
$ docker compose -f docker-compose.yml -f docker-compose.tls.yml config --services
jc-mysql
jc-server
jc-nginx
```

服务名问题已经修了，但 `tls.conf` 仍是另一份精简配置：没有 `limit_req`（TLS 模式下 API 不限流）、没有访问日志脱敏（`token` 可能进日志）、没有 `/ws/`、没有 MJPEG 不缓冲、没有 `/assets/` 缓存。**“能起来”不等于“能交付”**——TLS 模式现在仍然比 HTTP 模式弱。

### 3.8 协议标准化

| 对比项 | 工业级做法 | 我们现状 | 等级 |
|---|---|---|---|
| 机器人 | VDA5050 / Open-RMF / 厂商 SDK + 适配器 | JCROB 私有 HTTP；VDA5050 只映射状态名 | 缺（多厂商） |
| 传感器 | Modbus RTU/TCP、OPC UA、Sparkplug B | Modbus TCP 03/04（一寄存器一连接）；MQTT QoS 0 | 弱 |
| 视频 | GB28181/ONVIF/RTSP + NVR | go2rtc + ffmpeg，2 路，手工 RTSP | 缺（国标场景） |
| 对外 API | OpenAPI + 版本化 + 幂等键 + 错误码 | 有 OpenAPI/Pydantic；无版本化/幂等键/弃用策略 | 弱 |
| 数据契约 | JSON Schema/Avro + 单位/时区/枚举 | Pydantic + `units.py` + fixtures；单位/时区仍靠约定 | 够用 |
| 一致性测试 | conformance suite / 仿真器 | 有 JCROB 模拟器 + fixtures + 73 个后端用例 | 弱 |

**判断**：单厂商单站点，**私有协议不是错**，错的是没有“内部 canonical model”。现在 `robot.status`、`sensor.value`、`alarm.metric` 三套语义各写各的；换一家设备，适配器能换，但告警/报表/点位要跟着改。近期最该做的是**统一内部设备模型**（id、类型、能力、单位、时间戳、错误码、幂等键），而不是追外部标准。

### 3.9 额外：防爆/作业领域的缺口（不在八维内，但影响“工业级”叙事）

| 能力 | 工业级做法 | 我们现状 | 建议 |
|---|---|---|---|
| 防爆设备台账 | Ex 证书、温度组别、区域等级、检验有效期 | 设备表只有型号/协议/IP | 二期加字段与到期提醒 |
| 作业票/许可 | 动火/受限空间/临时用电与机器人作业联动 | 无 | 二期，EHS 集成 |
| 气体联锁 | 可燃气体超限自动禁止机器人进入/自动撤离 | 只有告警，无联锁 | 需与机器人/门禁联动，单平台做不到 |
| 人员/电子围栏 | UWB/定位标签 + 区域禁入 | 无 | 二期 |
| 功能安全 | 安全 PLC/急停回路/安全等级认证 | 平台明确不承担（正确） | 保持边界，不要宣传“平台急停” |

**边界要写死**：平台是 L3 作业层，**不能替代安全回路、不能替代硬件急停、不能承担防爆认证**。这一条现在文档里有，但对外材料要反复讲。

---

## 4. 按投入产出排序的补齐清单

排序原则：**先做“出了事能兜住”的，再做“规模化”的；先做 1–3 人日的，再做 10 人日以上的。**
人天按“熟悉这套代码的 1 名后端 + 0.5 名前端”估算，含自测与文档，不含真机联调等待。

| # | 事项 | 解决什么问题 | 最小实现 | 人天 | 不做会怎样 | 批次 |
|---|---|---|---|---|---|---|
| 1 | TLS 收尾 + 生产开关 | `tls.conf` 比 HTTP 配置弱；`/docs` 暴露；DB 默认口令不校验 | 把 `default.conf` 的 `limit_req`/safe log/`/ws/`/MJPEG 不缓冲/静态缓存合并进 `tls.conf`；`JC_DOCS_ENABLED=false` 写进 env 并在 `assert_production_safe()` 校验；`docker compose config` 进 CI | 1 | 甲方安全扫描/等保 checklist 直接挂；TLS 模式反而更弱；Cookie 无 Secure | **12 月前** |
| 2 | 采集并行收口 | 慢网络误判离线；部分失败误恢复告警 | 修 `galileo` 未定义；四路 `gather` + 每路独立 `timeout`/jitter；`StateCache` 按字段保存 `last_good` + `fetched_at`；只有全成功才刷新 `recv_ts`；部分成功标 `partial`，告警用真实 `age_s`、不触发 `resolve` | 1 | 网络半坏时低电量/急停告警“自己好了”；页面显示“在线 0s”但数据是空的；当前还会因 `NameError` 导致告警静默 | **12 月前** |
| 3 | `/metrics` + 6 条告警 + 死信 | 平台/库/轮询/录像/磁盘挂了没人知道 | `prometheus-client` 暴露 8 个指标；`monitoring` compose profile（Prometheus+Grafana+node_exporter+mysqld-exporter）；告警走现有 webhook；主机 cron 探 `/health` 三次失败发通知 | 3 | 黑屏/停录/库挂只能等客户打电话；验收“失联”项没有客观证据 | **12 月前** |
| 4 | 日志留存 180 天 | 事故只能复盘几小时；等保 6 个月不满足 | `RotatingFileHandler` 写 `/app/logs/app.log`（100MB×30）+ 每月 gzip 归档到 NAS；nginx access log 保留 180 天；日志加 request id | 1.5 | 出事无法定位；等保/审计过不了；客户问“昨天的日志”拿不出 | **12 月前** |
| 5 | 备份加密 + 异地 + 恢复演练 | 主机/磁盘/勒索 = 数据全丢 | `age` 加密；`rsync` 到 NAS/另一台机；sha256 清单；每周自动恢复到临时库校验行数；RPO 24h/RTO 1h 写进 runbook | 3 | 一次磁盘故障就交付事故；审计链/录像索引无法恢复 | **12 月前** |
| 6 | 录像/视频看护 + 冻结检测 | go2rtc 单点；告警时黑屏 | systemd 守护 go2rtc（Restart=always）；后端每 10s 探 `/api/streams`；`/videos/{id}/health` 返回最后一帧时间；连续 3 次失败告警；UI 显示“画面冻结” | 2.5 | 关键时刻无画可查；工单/告警没有视频证据 | **12 月前** |
| 7 | 保留策略补全 + 容量看板 | 环境读数无限长；磁盘满自动停录 | `sensor.keep_days=90` 已有 **[工作区]**，但需改分批删；再补 `message` 90 天、`notify_log` 90 天、`login_attempt` 30 天、`operation_log` 180 天后归档；表大小/磁盘/录像天数上看板 | 1.5 | 磁盘先满 → 停录 → 关键证据丢；首删 1,550 万行会锁表 | **12 月前** |
| 8 | 坐标标定校验 + 下发幂等/对账 | 点位错 → 车走错；重复下发/重启假 running | 两点标定求相似变换，残差 >0.5m 或尺度误差 >5% 拒绝保存；`TaskRun` 加 `client_order_id` 唯一 + `order_update_id`；启动查 `get_order()` 接管或失败；取消与巡航线程竞态收口 | 5 | 验收“定位/任务”两项直接失败；现场撞/停摆 | **12 月前** |
| 9 | 事件录像 + 证据包 | 告警与录像对不上，客户不认 | 告警触发保存前 10s/后 30s 片段；生成 `manifest.json`（alarm_id、camera_id、起止、sha256）；告警详情直接播 | 2 | 事故复盘靠人翻文件夹；争议时没有可验证证据 | 12 月前（可裁剪） |
| 10 | 验收证据一键导出 | 验收现场手工翻库，慢且易错 | `/reports/acceptance` 打 zip：审计链校验、告警 KPI、任务执行记录、断网测试日志、容量报告、配置快照（脱敏） | 2 | 验收拖时间；口说无凭 | 12 月前（可裁剪） |
| 11 | 报警治理 KPI | 告警泛滥没人管；无法证明“告警有效” | 统计 top-N 最吵测点、10 分钟告警数、确认/处置时长、长期 standing 告警；日报/周报 | 1.5 | 值班被淹没；验收问“告警准确率”答不上 | 验收后 2 周 |
| 12 | MQTT QoS1/LWT/异步入库 | 断线丢读数；paho 线程被 DB 阻塞 | `qos=1`、`will_set`、`retain` 按主题；`on_message` 只入队，独立线程批量写库；主题规范 `jc/{site}/{device}/{metric}` | 2 | 传感器断线数据丢失；高并发丢消息 | 二期 |
| 13 | 内部 canonical 设备模型 | 换设备要改告警/报表/点位 | 定义 `Device{id,type,capabilities,units,ts,error_code}`；适配器只做映射；告警/报表只读 canonical | 5 | 每接一家设备重写一遍业务 | 二期 |
| 14 | 时序库 + 聚合 | 遥测 7 天不够；报表全量加载 | TimescaleDB/VictoriaMetrics；1min 聚合；按天/月分区；报表走聚合表 | 8–12 | 50 台时查询 OOM；180 天追溯做不到 | 二期 |
| 15 | 集中日志 + trace | 多容器排障靠猜 | Loki + Promtail；OpenTelemetry + request id；Grafana 统一看板 | 8–12 | 故障定位以小时计 | 二期 |
| 16 | OPC UA / Sparkplug 接入 | 接不了 DCS/PLC/多厂商 | PLC4X sidecar 或 `asyncua`；Sparkplug B 主题/别名；点表配置化 | 10–15 | 每个新厂都要定制开发 | 二期 |
| 17 | GB28181 / NVR | 客户已有国标平台/多路相机 | ZLMediaKit + wvp-pro；或 MediaMTX 过渡；ONVIF 发现；硬件转码 | 10–20 | 视频只能单厂 2 路，扩不了 | 二期 |
| 18 | MySQL HA + 双实例 | 主机挂了停服 | InnoDB Cluster/Patroni + 双 app + HAProxy；或接受冷备 | 15–25 | RTO 以小时计 | 二期/三期 |
| 19 | VDA5050 / Open-RMF | 多厂商车队/客户指定标准 | VDA5050 adapter + MQTT 契约 + conformance 用例；Open-RMF 仅在 >3 台时 | 12–20 | 车队项目投不了标 | 三期，条件触发 |
| 20 | 边缘 store-and-forward | 现场断网丢数据 | 边缘网关本地队列 + 序列号 + 补传；平台幂等接收 | 20–40 | 断网期间巡检记录缺失 | 三期 |
| 21 | SSO/OIDC + mTLS | 客户 AD/等保三级 | Keycloak + OIDC；服务间 mTLS；API Key 轮换 | 8–12 | 大客户 IT 不批 | 三期 |
| 22 | 3D 数字孪生 | 演示/汇报 | 不要自研渲染；用现成引擎做数据皮肤 | 30–60 | 不影响一期验收 | 永远不急 |
| 23 | AI 闭环 | 表计/缺陷识别 | 接外部算法盒（已有 `/ai/results`），平台只做人工确认与工单 | 10–20 | 不是一期合同 | 二期 |

### 4.1 如果只有 10 人日

按顺序做 **1 → 2 → 3 → 4 → 5**（TLS、采集并行、metrics、日志、备份）。
理由：这五项都是“出事能兜住”，且不依赖真机；任何一项缺席，验收现场都可能变成事故现场。

### 4.2 如果有 25 人日

做 **1–8**（加上录像看护、保留策略、坐标/幂等）。
理由：覆盖验收的“定位、任务、告警、失联、审计”五项，且把最可能的三类事故（撞机、监控瞎火、告警被吃掉）都堵上。

### 4.3 如果有 50 人日

加 **9–13**（事件录像、证据导出、告警 KPI、MQTT 加固、canonical 模型）。
仍然**不要**碰 14–21：那些是二期规模化的活，12 月前做完也无法验证。

### 4.4 `/metrics` 最小指标集（对应 #3）

```text
jc_up{service="server"}                         1/0
jc_db_up                                        1/0
jc_robot_online{robot="1"}                      1/0
jc_poll_age_seconds{robot="1"}                  最后成功采样年龄
jc_poll_failures_total{robot="1",reason="..."}  累计失败
jc_alarm_open{level="critical|warn"}            未关闭告警数
jc_alarm_ack_seconds                            确认时长直方图
jc_http_requests_total{method,path,status}      RED 指标
jc_loop_lag_ms                                  事件循环延迟
jc_recording_active                             正在录制路数
jc_disk_free_bytes{path="/data"}                磁盘余量
```

配套 6 条告警规则（阈值可按现场调）：

| 规则 | 表达式（示例） | 持续 |
|---|---|---|
| 平台宕机 | `up{job="jc-server"} == 0` | 1m |
| 数据库断 | `jc_db_up == 0` | 1m |
| 机器人数据过期 | `jc_poll_age_seconds > 10` | 2m |
| 录像停了 | `jc_recording_active == 0` 且业务时段 | 5m |
| 磁盘不足 | `jc_disk_free_bytes < 8*1024^3` | 5m |
| 事件循环卡 | `jc_loop_lag_ms > 100` | 5m |

> 这些指标全部能从现有 `health_deep` / `StateCache` / `AlarmStore` / `recorder` / `disk_monitor` 取到，不需要新表、不需要改业务逻辑。

### 4.5 备份/恢复最小 runbook（对应 #5）

```bash
# 1) 每日 02:00：全量 + 加密 + 校验
mysqldump -h127.0.0.1 -ujcrob -p"$JC_DB_PASSWORD" \
  --single-transaction --routines --triggers jcrob \
  | age -r "$AGE_PUB" > /backup/jcrob-db-$(date +%F).sql.age
sha256sum /backup/jcrob-db-$(date +%F).sql.age >> /backup/SHA256SUMS

# 2) 同步到 NAS/另一台机（异地）
rsync -a --delete /backup/ nas:/volume1/jcrob-backup/

# 3) 每周日：恢复到临时库，校验行数 + 审计链 + 登录
age -d -i "$AGE_KEY" /backup/jcrob-db-$(date +%F).sql.age \
  | mysql -h127.0.0.1 -uroot -p"$MYSQL_ROOT_PASSWORD" jcrob_restore
mysql -e "SELECT COUNT(*) FROM jcrob_restore.alarm_record;"
curl -fsS http://127.0.0.1:8099/health
```

> 关键不是“有 dump”，而是**每周真的恢复一次**并把行数、审计链、登录结果留档；RPO 24h、RTO 1h 写进交付说明，别写“高可用”。

---

## 5. 12 月验收前：做什么、不做什么

> 假设：2026-12-01 交付、12 月验收；真机 11-10 到场。确切验收日期/评委/用例未在现有文档中确认（**不确定**）。

### 5.1 三周排期（与真机联调并行）

| 时间 | 必须完成 | 验收证据 |
|---|---|---|
| 10/23–10/31 | TLS 修复（#1）、采集并行（#2）、`/metrics` + 告警（#3）、日志留存（#4） | `docker compose config` 通过；Grafana 截图；断网/停录/库挂三类告警各触发一次；`/app/logs` 有 7 天文件 |
| 11/01–11/09 | 备份加密异地（#5）、保留策略（#7）、录像看护（#6）、坐标标定（#8 前半） | 恢复演练记录（生产 MySQL）；磁盘/表大小报告；go2rtc kill 后 30s 内自动恢复；两点标定残差报告 |
| 11/10–11/21 | 真机联调；下发幂等/对账（#8 后半）；事件录像（#9） | 20 次连续任务记录；重复点击/重启/拔网线三类异常录像；告警对应片段 |
| 11/22–11/30 | 证据导出（#10）、全链路演练、文档冻结 | 验收 zip；演练报告；回退矩阵 |
| 12/01–12/15 | **只修 bug**；不新增模块；不换架构 | 每日 bug 清单与回归 |

### 5.2 验收硬门槛（缺一不可）

- **定位**：两点标定 + 3 个已知点误差记录；误差 >0.5m 拒绝保存并给原因。
- **任务**：3 点任务连续成功 20 次；暂停/继续/取消；重复点击不重复下发；重启后不出现假 `running`。
- **告警**：急停/离线/超限可产生；critical 不被静默；确认→处置→关闭；通知可达；告警能回放对应视频。
- **失联**：拔网线 3s 内页面标“数据过期”，10s 内出离线告警，恢复后自动重连。
- **审计**：每个写操作可追到人/时间/参数/结果；`/audit-logs/verify` 返回 ok；导出可读。
- **灾备**：生产 MySQL 删库→恢复一次；RPO/RTO 写在交付说明里。
- **可观测**：一块屏能看到 server/db/robot/video/disk 五个状态；任一异常有告警。

### 5.3 验收前明确不做（写进范围说明）

| 不做 | 理由 | 什么时候 |
|---|---|---|
| MySQL 主从/双机 | 单站点，投入 15–25 人日，验收前无法验证故障切换 | 二期，客户要求 RTO<15min 时 |
| 时序库/180 天聚合 | 当前 7 天够验收；上时序库要改报表/查询 | 二期，>10 台或合同要求 |
| VDA5050/Open-RMF | 厂商不支持，做了也是假合规 | 三期，多厂商车队时 |
| GB28181/ONVIF | 本期 2 路，客户未明确国标 | 二期，客户有国标平台时 |
| 3D 数字孪生 | 与验收项无关，30–60 人日 | 永远不急 |
| AI 训练/算法本体 | 合同外，已有外部算法盒接口 | 二期，接算法盒 |
| K8s/微服务拆分 | 单机 3 容器，拆了只增加故障点 | 永远不做（本项目） |
| 多租户 SaaS | 私有化单客户 | 永远不做（本项目） |

### 5.4 范围冻结规则

- **11/20 后不再加新页面/新模块**；只修 P0/P1 bug。
- 任何“顺便加个功能”先记到二期清单，不在联调窗口动数据库 schema。
- 每次 schema 变更必须先备份 + 在 8.40 演练；迁移失败容器退出是好事，但不能没有回滚包。
- 演示只演示“连续成功 20 次”的功能；没跑过的功能不演。

---

## 6. 二期与“永远不做”

### 6.1 二期（2027 Q1–Q2，按触发条件）

| 优先级 | 事项 | 触发条件 | 人天 |
|---|---|---|---|
| P1 | 时序库 + 1min 聚合 + 分区 | >10 台或合同要 180 天 | 8–12 |
| P1 | 集中日志 + trace | 多容器/多厂区排障 | 8–12 |
| P1 | MQTT QoS1/LWT + 异步入库 | 传感器 >10 或断网补传 | 2–4 |
| P2 | OPC UA / Sparkplug | 客户有 DCS/PLC | 10–15 |
| P2 | GB28181/NVR/ONVIF | 客户有国标平台/多路相机 | 10–20 |
| P2 | 内部 canonical 设备模型 | 接第二家机器人 | 5–8 |
| P3 | MySQL HA + 双实例 | 合同要求 RTO<15min | 15–25 |
| P3 | 对象存储 + 证据不可变 | 录像/证据要长期保全 | 8–12 |
| P3 | SSO/OIDC + mTLS | 客户 AD/等保三级 | 8–12 |
| P3 | 边缘 store-and-forward | 现场网络不稳定/断网要求 | 20–40 |
| P4 | VDA5050/Open-RMF | 多厂商车队项目 | 12–20 |

### 6.2 永远不做也合理

| 不做 | 理由 |
|---|---|
| 自研 MQTT Broker | EMQX/Mosquitto 成熟，自研只增加故障点 |
| 自研时序数据库 | TimescaleDB/VictoriaMetrics 足够，自研是负 ROI |
| 自研 NVR/GB28181 栈 | ZLMediaKit/wvp-pro 已解决，自研要 6 个月 |
| 自研对象存储 | Garage/SeaweedFS/MinIO 足够；单机 2 路用本地盘即可 |
| Kubernetes / 微服务拆分 | 单机 3 容器，拆了只增加运维成本 |
| 区块链存证 | 哈希链 + 异地备份 + 外部锚定足够；区块链是营销词 |
| 单机 50 路 7×24 录像 | 容量/CPU 都不够；要上 NVR/对象存储/事件录像 |
| 自研 SLAM/导航 | 厂商负责；平台做“监督层”，不碰控制 |
| 多租户 SaaS | 私有化单客户，租户模型是纯成本 |
| 无厂商支持的 VDA5050 合规认证 | 做了也无法通过 conformance；不如把私有适配器做稳 |
| 验收前的 3D 数字孪生 | 与验收项无关，30–60 人日，必超期 |
| 自研 AI 训练 | 用外部算法盒，平台只做结果接入/人工确认 |

---

## 7. 不确定项（需要客户/厂家/现场确认）

1. **验收日期、评委、测试用例**：现有文档只写“交付 2026-12-01”，12 月哪一天验收、按什么用例打分，**不确定**。
2. **等保要求**：是否要过等保三级、是否要求 6 个月日志、是否要求国密/TLS 双证书，**不确定**；这直接决定 #4/#5/#1 的深度。
3. **GB28181/OPC UA 是否为合同项**：现有交付说明写“本期不做”，但 PPT/客户口头可能提过，**不确定**；若合同有，二期排期要前移。
4. **JCROB 是否支持 WS 推送/回调**：协议文档有 WS 3547，但当前 `capability` 里 `task_callback=False`，真机未验证，**不确定**；若支持，状态同步可从轮询切订阅，收益很大。
5. **go2rtc 谁维护**：它跑在宿主上、不在 compose 里，是现场 IT 还是我们装，**不确定**；若是我们，必须纳入交付清单和守护脚本。
6. **是否有 NAS/异地存储**：备份加密异地依赖客户提供 NAS 或另一台机，**不确定**；没有就只能退而求其次做“同机第二块盘”，不能算灾备。
7. **实际视频码率/路数**：录像 30 天/800GB 是否成立，取决于码率，**未实测**；按 2Mbps×2 路推算只能存约 18.5 天。
8. **机器人是否支持多任务并发/取消语义**：当前平台按“一车一任务”设计；厂商是否支持任务队列/取消确认，**不确定**。
9. **50 台/多厂区是否是真实需求**：现有合同是单台；若销售承诺了 50 路/多厂区，容量与架构要重算，**不确定**。
10. **VDA5050 最新版本号**：规范已到 3.x（2024-03 为 v3.0.0，之后还有新版），具体小版本以 VDA 官网为准，**本文不锁定版本**。
11. **MinIO 社区版后续**：2025 年底进入维护模式，未来是否恢复/变更许可，**不确定**；因此不建议新项目强依赖。
12. **现场 NTP/时钟源**：机器人/服务器是否统一 NTP，**不确定**；没有 NTP，所有“时间对不齐”的复盘都不可信。

---

## 8. 参考链接

### 机器人/车队/协议

- Open-RMF：[GitHub](https://github.com/open-rmf/rmf)、[rmf_ros2](https://github.com/open-rmf/rmf_ros2)、[RMF Book](https://osrf.github.io/ros2multirobotbook/)
- VDA5050：[规范仓库](https://github.com/VDA5050/VDA5050)、[V2.0 规范 PDF](https://www.vda.de/dam/jcr:f0c9c019-1506-4dee-998a-e92723fbf025/EN-VDA5050-V200.pdf)
- Apache PLC4X：[GitHub](https://github.com/apache/plc4x)、[官网](https://plc4x.apache.org/)
- ROS 2 Nav2：[GitHub](https://github.com/ros-navigation/navigation2)、[文档](https://docs.nav2.org/)
- openTCS（备选车队）：[GitHub](https://github.com/openTCS/opentcs)

### IoT 平台/消息/规则

- ThingsBoard：[GitHub](https://github.com/thingsboard/thingsboard)、[官网](https://thingsboard.io/)
- EMQX：[GitHub](https://github.com/emqx/emqx)、[官网](https://www.emqx.io/)
- Eclipse Mosquitto：[GitHub](https://github.com/eclipse-mosquitto/mosquitto)
- Node-RED：[GitHub](https://github.com/node-red/node-red)、[官网](https://nodered.org/)
- Sparkplug B：[Eclipse Sparkplug](https://sparkplug.eclipse.org/)
- OPC UA：[OPC Foundation](https://opcfoundation.org/about/opc-technologies/opc-ua/)

### 监控/日志/存储

- Prometheus：[GitHub](https://github.com/prometheus/prometheus)、[官网](https://prometheus.io/)
- Grafana：[GitHub](https://github.com/grafana/grafana)、[官网](https://grafana.com/)
- Grafana Loki：[GitHub](https://github.com/grafana/loki)
- OpenTelemetry：[官网](https://opentelemetry.io/)
- VictoriaMetrics：[GitHub](https://github.com/VictoriaMetrics/VictoriaMetrics)
- TimescaleDB：[GitHub](https://github.com/timescale/timescaledb)
- MinIO：[GitHub](https://github.com/minio/minio)、[官网](https://min.io/)、[社区版维护模式报道](https://www.infoq.com/news/2025/12/minio-s3-api-alternatives/)
- Garage：[GitHub](https://github.com/deuxfleurs-org/garage)
- SeaweedFS：[GitHub](https://github.com/seaweedfs/seaweedfs)
- restic：[GitHub](https://github.com/restic/restic)、[官网](https://restic.net/)

### 视频/SCADA/身份

- ZLMediaKit：[GitHub](https://github.com/ZLMediaKit/ZLMediaKit)
- wvp-GB28181-pro：[GitHub](https://github.com/648540858/wvp-GB28181-pro)
- MediaMTX：[GitHub](https://github.com/bluenviron/mediamtx)
- FUXA：[GitHub](https://github.com/frangoteam/FUXA)
- OpenSCADA：[官网](https://oscada.org/)
- Keycloak：[GitHub](https://github.com/keycloak/keycloak)、[官网](https://www.keycloak.org/)
- MySQL InnoDB Cluster：[官方文档](https://dev.mysql.com/doc/refman/8.4/en/mysql-innodb-cluster-introduction.html)

### 标准/合规

- ISA-18.2 报警管理：[ANSI/ISA-18.2-2016](https://webstore.ansi.org/standards/isa/ANSIISA182016)
- IEC 62443 工控安全：[ISA/IEC 62443 系列](https://www.isa.org/standards-and-publications/isa-standards/isa-iec-62443-series-of-standards)
- 等保 2.0：GB/T 22239-2019《信息安全技术 网络安全等级保护基本要求》
- 网络安全法：网络日志留存不少于 6 个月（第二十一条）
- 防爆：GB 3836 系列 / IEC 60079（设备防爆，不是平台软件能力）
- 机器人安全：ISO 10218 / ISO 3691-4（工业机器人/工业车辆安全，平台不替代安全回路）

> 许可提示：Grafana/Loki 为 AGPL-3.0，MinIO 为 AGPL-3.0，OpenSCADA 为 GPL；闭源交付不要复制代码进产品，只做**独立进程/独立服务**集成，商用前让法务核对仓库 LICENSE 原文。

---

## 附录 A：关键证据索引

| 结论 | 证据（file:line） | 等级 |
|---|---|---|
| 单进程单 worker | `deploy/entrypoint.sh:12-16`；`server/app/main.py:1-5` | 代码 |
| 基线每轮 4 个串行 HTTP；工作区已改 `gather` | `server/app/tasks/poller.py:29-32`；`server/app/services/robot_runtime.py:97-115` | 代码 |
| 并行收口未完成（`galileo` NameError、`age_s=0`、字段级新鲜度） | `server/app/services/robot_runtime.py:100-125`；`server/app/services/state_cache.py:35-50`；`alarms.py:_resolve_gone` | 代码（工作区） |
| 在线判定 5s、离线 10s | `server/app/services/state_cache.py`；`server/app/services/alarms.py:51-65` | 代码 |
| 遥测 10s/7 天 | `server/app/api/v1/telemetry.py:30-31,101` | 代码 |
| 设计写 1s/7天 + 1min/180天 + 分区 | `docs/平台方案-定稿.md` §12 | 文档 |
| 环境读数清理：工作区已加 90d，单条 DELETE | `server/app/main.py:140-155`；`server/app/services/settings_schema.py:sensor.keep_days` | 代码（工作区） |
| 录像最多 2 路 | `server/app/services/recorder.py:34` | 代码 |
| 报表全量加载 | `server/app/api/v1/reports.py:66,92,115` | 代码 |
| 报表缓存 `_summary_out` 未定义（500） | `server/app/api/v1/reports.py:223-224` | 代码（工作区） |
| 重启把任务标 failed | `server/app/main.py:71-83` | 代码 |
| 通知队列满丢告警 | `server/app/services/notify.py:154` | 代码 |
| 日志只写 stdout | `server/app/core/logging.py` | 代码 |
| Docker 日志上限 | `deploy/docker-compose.yml:27-28,61-62,84` | 配置 |
| TLS 服务名（评审开始时错误，工作区已修） | `deploy/docker-compose.tls.yml:4`；`deploy/docker-compose.yml:79` | 实测 |
| TLS 配置丢限流/脱敏 | `deploy/nginx/tls.conf` vs `deploy/nginx/default.conf` | 配置 |
| `/docs` 默认开启 | `server/app/core/config.py:40`；`deploy/env.example` 未设 `JC_DOCS_ENABLED` | 代码 |
| 7 角色 | `server/app/api/v1/users.py:27` | 代码 |
| API Key 4 scope + 过期 | `server/app/api/v1/api_clients.py:23`；`server/app/services/api_auth.py:24` | 代码 |
| 审计哈希链可整表重算 | `server/alembic/versions/0017_rechain_audit.py`；`server/app/services/messages.py:193-215` | 代码 |
| 备份本地 14 天不加密 | `deploy/backup.sh:14,46` | 代码 |
| 生产 MySQL 未演练 | `docs/生产风险评审与整改计划-20261022.md` §8（本机 SQLite 演练） | 文档 |
| VDA5050 只映射状态名 | `server/app/services/task_dispatch.py:25-32` | 代码 |
| 私有订单无幂等键 | `server/app/services/task_dispatch.py:_order_payload`；`server/app/models/task_run.py` | 代码 |
| Modbus 一寄存器一连接 | `server/app/services/sensor_gateway.py:_poll_modbus` / `modbus_read` | 代码 |
| MQTT QoS0 | `server/app/services/sensor_gateway.py:192` | 代码 |
| 前端 1s 轮询 | `web/src/stores/robot.ts:4` | 代码 |
| nginx 配了 `/ws/` 但后端无 WS | `deploy/nginx/default.conf:91`；`server/app` 无 `@router.websocket` | 代码 |
| 平台自身无 metrics | 全仓无 `prometheus`/`opentelemetry` 依赖与端点 | 代码 |

## 附录 B：容量测算（推算，未压测）

| 项 | 公式 | 结果 |
|---|---|---|
| 遥测（当前 10s） | 86400 / 10 × 台数 | 8,640 行/台/天；50 台 = 43.2 万行/天 |
| 遥测（设计 1s） | 86400 × 台数 | 8.64 万行/台/天；50 台 = 432 万行/天、15.8 亿行/年 |
| 环境读数（5s） | 86400 / 5 × 测点数 | 10 测点 = 17.28 万行/天、6,300 万行/年 |
| 录像（2 路 2Mbps） | 2 × 2Mbps ÷ 8 × 86400 | 43.2 GB/天；800GB ≈ 18.5 天 |
| 录像（2 路 1Mbps） | 2 × 1Mbps ÷ 8 × 86400 | 21.6 GB/天；800GB ≈ 37 天 |
| 报表内存（7 天） | 台数 × 8,640 × 7 | 1 台 6 万行；50 台 302 万行，`.all()` 进内存有 OOM 风险 |
| 日志上限 | server 20MB×5 + mysql 20MB×5 + nginx 10MB×3 | 约 230MB；按 1GB/天访问日志只能存几小时 |

> 以上均为按代码路径的**推算**，不是实测。真机到场后应用真实码率/请求量重算，并写进交付说明。

---

## 附录 C：一句话给不同读者

- **给老板**：单机能交付，但“工业级”三个字现在撑不住；12 月前把备份、监控、录像、坐标四件事做实，验收能过；HA/时序库/国标是二期。
- **给研发**：先修 §4 的 1–8；不要碰 §6.2；每次改 schema 先备份；所有写操作加幂等键。
- **给现场**：平台不是急停，不能远程停车；失联时车端自治；录像/告警/审计每天看一眼；备份每周验一次。
- **给客户**：一期是“单厂商单站点巡检闭环”；多厂商/多厂区/国标级联是二期，需要另立合同。
