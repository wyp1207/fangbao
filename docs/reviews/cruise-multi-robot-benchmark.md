# 巡检巡航 / 任务下发 / 多机调度 / 定位初始化 —— 成熟方案对标报告

> 目的：把 Open-RMF、VDA5050、Nav2 里已经踩过的坑，映射到我们这套「平台逐点下发 + 轮询到点」的实现上，给出可直接开工的改造清单。
> 编写日期：2026-10-27 ｜ 适用代码：`server/app/services/cruise.py`、`task_dispatch.py`、`adapters/*`
> 可信度说明：ROS/RMF/Nav2/VDA5050 部分的字段级事实来自官方文档、官方 API 文档与 `vda5050-types`（其字段注释逐条摘自 VDA5050 规范正文），链接均给出；商用厂商部分公开资料以宣传稿为主，只能提取架构级信息，已在第 1 节与第 9 节标注可信度边界。

---

## 0. 一页结论（先看这个）

1. **我们不是"选错了逐点下发"，而是"没有能力协商"**。JCROB 的 `dispatch` 能把整条 `sub_tasks` 一次发下去（[http_adapter.py:197](../../server/app/adapters/jcrob/http_adapter.py#L197)），X30 的 1003 一次只接一个目标（[adapter.py:126](../../server/app/adapters/deeprobotics/adapter.py#L126)）。平台为了兼容取了两者的交集 = 逐点。正确做法是把"整单 / 逐点"变成适配器声明的 `exec_mode`，而不是写死在巡航执行器里。
2. **VDA5050 之所以用"完整订单 + 节点/边 + 状态回传"，核心是四点**：订单可去重（`orderId`+`orderUpdateId`）、可断点续跑（`lastNodeId`/`lastNodeSequenceId`）、可局部改单（`released` 区分 base/horizon）、可判"到点"（`nodePosition.allowedDeviationXY` + `nodeStates` 收缩）。我们目前这四样一个都没有落到数据结构上。
3. **"到点"不能只看车端状态字**。行业是"多信号与门"：坐标容差 + 姿态容差 + 速度≈0 + 停留时间 + 车端节点 REACHED + 定位质量。我们现在只做了"FINISHED + 距离复核"（[cruise.py:257](../../server/app/services/cruise.py#L257)），缺速度、缺角度、缺停留、缺定位质量。
4. **多机防死锁的正确姿势是"预约 + 单一持有者 + 超时回收"，不是"抢占"**。RMF 用交通日程库 + 协商表（提出 itinerary、第三方 evaluator 裁决）；我们规模小（N 台、无路网），最小可用版是一张 `resource_lock` 表 + 单机并发=1 + 关键区互斥 + 死锁环检测 + TTL 强拆。
5. **定位初始化必须是"状态机 + 策略"，不能是一个按钮**。断电重启、被搬动、切图/换楼层、定位质量掉底，这四类事件必须自动触发重定位，且初始化后要**校验**（走 1 m 看位姿是否自洽），否则就是"初始化成功、导航跑偏"。
6. **地图与点位要版本化**。VDA5050 明说"每层一张图、各图原点一致"；我们 `PlatformMap` 有 `floor`/`origin_*` 但点位没绑地图版本——重建图那天，所有点位坐标会静默失效。
7. **两套下发链路（`task_dispatch.dispatch` 整单 / `cruise` 逐点）并存，是当前最大的结构性债务**：状态机语义不一致、看门狗只认 `last_progress_at`、取消要停线程再发车端取消（[task_runs.py:424](../../server/app/api/v1/task_runs.py#L424)）。

---

## 1. 对标对象与关键机制速览

| 方案 | 管什么 | 关键机制（原文级事实） | 对我们的含义 | 链接 |
|---|---|---|---|---|
| **Open-RMF / rmf_traffic** | 多机型、多厂商、共享空间的交通去冲突 | ①**交通日程库**：所有车把"未来轨迹"登记进中央 schedule；②**冲突→协商**：日程检出冲突后通知各车队，各队提交偏好 itinerary，**第三方 judge（evaluator）裁决**；③`Negotiation` 提供 `Table`（按"谁迁就谁"的层级视图）、`ready()`/`complete()` 判据 | 我们没路网、没轨迹，**不宜照搬协商**；但"登记意图 + 裁决者"的思想可用于"资源锁 + 排队" | [RMF Core Overview](https://osrf.github.io/ros2multirobotbook/rmf-core.html) ｜ [Negotiation API](https://openrmf.readthedocs.io/projects/rmf-traffic/en/latest/api/classrmf__traffic_1_1schedule_1_1Negotiation.html) |
| **RMF 车队控制分级** | 异构车队的接入下限 | 明确 4 档：`Full Control`（读位姿+指定路径+暂停/恢复+读电量+推断到达）／`Traffic Light`（只读位姿+暂停恢复）／`Read Only`（只读）／`No Interface`（不兼容）。并写明：**同一共享空间最多只能有一个 Read Only 车队**，否则"几乎不可能避免死锁" | 直接就是我们的"多厂商车接入分级"模板。X30 有 cancel 无 pause、JCROB 无 pause，属于 `Traffic Light` 偏下；对这类车**不能让它参与互斥资源的持有** | [同左 §Fleet Adapters](https://osrf.github.io/ros2multirobotbook/rmf-core.html) |
| **rmf_task** | 任务生命周期与"可恢复" | `Task::Active` 暴露 `backup()`（带序号的检查点，只保留最大序号）、`interrupt(cb)` 返回 `Resume`（人工接管/消防等紧急介入后恢复的凭据）、`cancel()`（优雅，允许继续做完收尾 phase）、`kill()`（立刻回安全态）；进度用 `pending/active/completed` 三段 phase 表达 | 我们的 `paused_at` 只是一个时间戳，**没有"接管凭据"，也没有检查点**；`from_seq` 是雏形但没有落成备份语义 | [Task Class API](https://docs.ros.org/en/ros2_packages/rolling/api/rmf_task/generated/classrmf__task_1_1Task.html) |
| **RMF 任务分配** | 多机派单 | Dispatcher 广播 `BidNotice` → 各车队回 `BidProposal`（含 cost，由 `TaskPlanner` 算）→ 裁决 → `DispatchRequest`；电量不足时**自动插入 ChargeBattery 任务**；每个充电位在地图里用 `is_charger` 标注 | 我们"一个平台管 N 台车"迟早要派单；bidding 太重，用"能力过滤 + 成本排序（距离/电量/当前负载）"即可，但要留 `cost` 字段 | [Tasks in RMF](https://osrf.github.io/ros2multirobotbook/task.html) |
| **RMF 路网资源** | 门/电梯/充电桩/停靠点 | 路网 lane 上挂事件：`Door`/`DoorOpen`/`DoorClose`、`Lift`/`LiftMove`/`LiftSessionBegin/End`、`Dock`、`Wait`——**把"占资源"变成路径上的一个必经事件** | 我们不需要路网，但"资源=路径上的显式占有点"这个抽象值得抄：`acquire/resource` 应挂在 step 上而不是散落在代码里 | [rmf_traffic API 类目录](https://openrmf.readthedocs.io/projects/rmf-traffic/en/latest/api/classrmf__traffic_1_1agv_1_1Graph_1_1Lane_1_1LiftMove.html) |
| **VDA5050 v2/v3** | AGV/AMR 与调度系统之间的通信标准 | 订单 = `orderId` + `orderUpdateId` + `nodes[]` + `edges[]`；每个 node/edge 带 `sequenceId` 与 `released`（true=base 已承诺 / false=horizon 可改）；`nodePosition` 带 `allowedDeviationXY/Theta`、`mapId`；动作带 `blockingType`（NONE/SOFT/HARD）；状态回传 `orderId`+`orderUpdateId`+`lastNodeId`+`nodeStates[]`/`edgeStates[]`/`actionStates[]`（WAITING→INITIALIZING→RUNNING→PAUSED→FINISHED/FAILED）+ `agvPosition{positionInitialized, localizationScore, deviationRange}` | 这是**"平台下发"这件事的参考数据模型**，即使不实现协议，字段设计也该照抄 | [VDA5050 v2.0 规范 PDF](https://www.vda.de/dam/jcr:f0c9c019-1506-4dee-998a-e92723fbf025/EN-VDA5050-V200.pdf) ｜ [Order 结构](https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/order/struct.Order.html) ｜ [NodePosition](https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/common/struct.NodePosition.html) ｜ [State](https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/state/struct.State.html) ｜ [AgvPosition](https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/common/struct.AgvPosition.html) ｜ [Action/BlockingType](https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/action/struct.Action.html) ｜ [InstantActions](https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/instant_actions/struct.InstantActions.html) |
| **ROS2 Nav2** | 单机导航栈 | `bt_navigator` 用行为树 XML 编排（可替换、可加恢复分支），对外是 `NavigateToPose` / `NavigateThroughPoses` 两个 action；`waypoint_follower` 用 `FollowWaypoints` 收一串位姿后**逐点**调 `NavigateToPose`（失败默认停）；AMCL 用 `/initialpose` 注入先验，另有"全局重定位"插件 | 我们的"逐点"其实等价于 `FollowWaypoints`；想要"一次下发"就是 `NavigateThroughPoses` 或"车端整单" | [Waypoint Follower](https://docs.nav2.org/rolling/configuration_and_development/configuration_guide/core_servers/waypoint_follower/) ｜ [BT Navigator](https://docs.nav2.org/rolling/configuration_and_development/configuration_guide/core_servers/configuring_bt_navigator/) ｜ [ThroughPoses 行为树](https://docs.nav2.org/behavior_trees/trees/nav_through_poses_recovery.html) |
| **Nav2 生命周期** | 节点可控启停 | 托管节点 `unconfigured→inactive→active→finalized`，由 `lifecycle_manager` 按 `bond` 心跳统一拉起/监控；参数改动要 `configure` 才生效 | 我们适配器是"每次请求现建对象"，没有 warm/standby 概念；真要保 SLA 需要"连接池 + 心跳 + 退避重连" | [Nav2 Configuration Guide](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/) |
| **rmf_demos / free_fleet / patrol 类** | 巡检巡航的开源实现 | RMF 有 `dispatch_patrol`：给一串地点 + 循环次数（`-p lounge supplies pantry -n 2`），可指定车队/车号，有 task id 可 cancel；`free_fleet` 是 RMF fleet adapter 的 Python 实现（zenoh 跨机），其 TODO 里明确写着"**map switching support**"未做 | ①巡航道 = 地点列表 + 循环次数，这是行业通行抽象；②"切图未支持"连成熟开源都没解决，我们必须自己做且要做对 | [rmf_demos_tasks README](https://docs.ros.org/en/ros2_packages/rolling/api/rmf_demos_tasks/README.html) ｜ [free_fleet](https://github.com/open-rmf/free_fleet) ｜ [fleet_adapter_template](https://github.com/open-rmf/fleet_adapter_template) ｜ [ros2_patrol_robot](https://github.com/ruali-dev/ros2_patrol_robot) ｜ [PlanSys2 巡逻示例（PDDL 规划巡逻序列）](https://github.com/IntelligentRoboticsLabs/ros2_planning_system_examples/tree/master/plansys2_patrol_navigation_example) |
| **国自 GRACE Xpress 2.0（商用）** | 千台级调度/交通/标定 | 公开稿给出三个数字：调度算法"单场景实时调度 **2000+ 台**、**1 秒内**分配任务至单台"；交通算法"支持 **10 万㎡**、2000+ 台路线管理"；另有"**AGV 自标定算法**：用日常运行数据在线校正参数，减少人工标定" | ①说明商用系统的护城河在"交通 + 标定"，不在"下发协议"；②"自标定"正是我们要补的"漂移自愈" | [国自 GRACE Xpress 2.0](https://www.zidonghua.com.cn/news/newproduct/61708.html) |
| **国自 太重项目（商用）** | 异构混行 | "近 200 台不同种类、负载的机器人"在同一厂区跑 | 异构是常态，不是特例；能力矩阵必须一等公民 | [国自新闻](https://www.gzrobot.com/news/708275604058181/708986583388229) |
| **亿嘉和（商用）** | 电厂巡检集群 | 公开口径是"**站端+集控**双轮驱动"、"**云—边—端**架构下多机协同、智能联动"；产品矩阵 OE200（四足）/D200（操作）/SI300/A200（挂轨）；方向是从"单场景能干"到"多机联动" | **架构结论**：站端（本地调度、断网可跑）+ 集控（跨站/跨机统筹）两层，正是我们该摆的位置——我们是"集控"，不该把实时闭环全压在平台 | [亿嘉和 2026 发电行业会议报道](http://stock.10jqka.com.cn/20260827/c679346996.shtml) ｜ [申昊×优必选战略合作（同为电力巡检生态）](https://www.gkzhan.com/news/detail/193138.html) |

---

## 2. A. 任务下发模型：一次下发 vs 逐点下发

### 2.1 三种模型，不是两种

| 模型 | 形态 | 优点 | 缺点 | 现实代表 |
|---|---|---|---|---|
| **A1 逐点**（我们现在） | 平台 `goto(p1)` → 等 FINISHED → `goto(p2)` … | ①平台完全掌握进度，每点可插动作、可跳过；②对车端能力要求最低（只需"发目标+查状态"）；③单点失败可局部重试；④调试、复现容易 | ①N 次往返、N 次定位收敛，走-停-走，**平均速度低**；②丢包/超时点要平台兜；③车端看不到整条路线，**无法与交通/资源协同**；④断网即断链，任务语义散在平台内存线程里；⑤一条巡航 = N 次"下单"，**没有任务级幂等** | 我们 `cruise.py`；Nav2 `FollowWaypoints`（服务端逐点调 `NavigateToPose`，本质仍是走-停-走） |
| **A2 整单**（VDA5050 / JCROB `sub_tasks`） | 一次发 `order{nodes,edges,actions}` → 车端自己跑 → 持续回 `state` | ①车端全局规划、连续运动、能耗低；②**一次 ACK 明确受理**，状态机干净；③`lastNodeId` 天然支持断点续跑；④网络抖动容忍（车端自主执行）；⑤任务级幂等（orderId）；⑥整段路线可参与调度协商 | ①平台对中间过程可见性**完全依赖车端状态回传质量**；②车端能力参差，必须留 fallback；③改单要走 `orderUpdate`，实现成本高；④**初始定位错了，整车整单跑偏** | VDA5050；JCROB `sub_tasks` |
| **A3 批量航点 / base-horizon** | 一次给一串位姿，但保留"逐点确认" | 折中：减少往返，又能在每点插动作/校验 | 协议复杂；车端要支持队列与变更 | Nav2 `NavigateThroughPoses`（连续过点不停）、VDA5050 `released=false` 的 horizon |

### 2.2 VDA5050 为什么坚持"完整订单 + 节点/边 + 状态回传"

不是为了好看，是四条硬需求逼出来的（字段语义均摘自规范）：

| 需求 | VDA5050 的做法 | 原文依据 |
|---|---|---|
| **幂等/去重** | `orderUpdateId` "unique per `order_id`；**若订单更新被拒绝，该字段必须随拒绝消息回传**" | [Order.order_update_id](https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/order/struct.Order.html) |
| **断点续跑** | 状态里回 `last_node_id` / `last_node_sequence_id`；续发订单时起点必须与之对齐（否则车端无从判断"我从哪接"） | [State.last_node_id](https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/state/struct.State.html) |
| **局部改单** | `Node.released=true` 属 base（已承诺），`false` 属 horizon（可被新单替换）；`sequenceId` 跨 node/edge 统一编号，"用来区分同一 order 内重复经过的同一节点" | [Node](https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/order/struct.Node.html) |
| **可判"到点"** | 节点上直接带 `allowedDeviationXY`（"AGV 在容差半径内通过即视为已穿越该节点"）与 `allowedDeviationTheta` | [NodePosition](https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/common/struct.NodePosition.html) |
| **可判"做到哪一步"** | `nodeStates` / `edgeStates` 只列"还没走完的"，随进度收缩；`actionStates` 带 `WAITING/INITIALIZING/RUNNING/PAUSED/FINISHED/FAILED` + `resultDescription` | [State](https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/state/struct.State.html) |
| **平台知道该不该继续发** | `new_base_request=true` = "车快到 base 末尾了，请发新 base"；这是**唯一正确的"增量下发"触发信号**，不靠轮询猜 | [State.new_base_request](https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/state/struct.State.html) |
| **动作与移动的关系** | `blockingType`：`NONE`（可与移动并行）/`SOFT`（可并行但不能移动）/`HARD`（独占） | [Action](https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/action/struct.Action.html) |

> 一句话：**整单不是"图省事"，是把"任务"变成一个可被引用、可被改、可被恢复、可被裁决的实体**。逐点下发把任务切成了 N 个互不相识的 RPC。

### 2.3 我们现状（代码级）

| 事实 | 位置 | 后果 |
|---|---|---|
| 巡航 = 一个 run 一个线程，逐点 `goto` + 3 s 轮询 + 单点 240 s 超时 | [cruise.py:26-27](../../server/app/services/cruise.py#L26)、[:84-128](../../server/app/services/cruise.py#L84) | 线程即状态机；进程重启 = 任务丢失（`main.py` 启动时把残留 `running` 标 `failed`） |
| 也有一条"整单"链路 `_order_payload`（actionId=`a{seq}`，带坐标） | [task_dispatch.py:117-141](../../server/app/services/task_dispatch.py#L117) | 但 `X30.dispatch` **只取 `actions[0]`**（[adapter.py:130](../../server/app/adapters/deeprobotics/adapter.py#L130)），整单对 X30 是假的 |
| JCROB 侧真能整单（`sub_tasks` 顺序执行 nav/image/sleep） | [http_adapter.py:197-221](../../server/app/adapters/jcrob/http_adapter.py#L197) | 能力被平台"拉平"成最弱的那台车 |
| 订单没有 `orderId` 稳定性：`JC-{毫秒时间戳}` 每次调用都变 | [task_dispatch.py:123](../../server/app/services/task_dispatch.py#L123) | **重发 = 新车端任务**，幂等完全靠人 |
| `external_id` 只有普通索引，无唯一约束 | [task_run.py:37](../../server/app/models/task_run.py#L37) | 重复上报可产生两条 |
| 状态 5 态：planned/running/done/failed/cancelled，`PAUSED` 被映射成 `running` | [task_dispatch.py:29-35](../../server/app/services/task_dispatch.py#L29) | 暂停不可见；"已下发未确认"这一态缺失，只能靠 30 s 看门狗猜 |

### 2.4 平台侧状态机（建议直接照这个改）

```
planned ──lock──▶ queued ──send──▶ dispatched ──ack──▶ running ──┬─▶ succeeded
   │                │                  │                  │      ├─▶ failed
   │                │                  │                  ├─pause▶ paused ─resume─▶ running
   └──cancel────────┴──────────────────┴──────────────────┴─cancel▶ cancelled
                                             │
                                             └─timeout/lost─▶ unknown ──reconcile──▶ running|failed
```

| 状态 | 进入条件 | 允许的下一态 | VDA5050 对应 | 我们现状 |
|---|---|---|---|---|
| `planned` | 从模板生成计划 | `queued` / `cancelled` | 无（单在平台侧） | ✅ 有 |
| `queued` | 已抢到机器人锁 + 资源锁 | `dispatched` / `cancelled` | 无 | ❌ 缺（现在 `assert_free` 是"用前检查"不是"占位"） |
| `dispatched` | 订单已发出，**未被车端确认** | `running` / `failed` / `unknown` | 车端 `state.orderId` 尚未变 | ❌ 缺（写库就直接 `running`） |
| `running` | 车端回显本次 `orderId`+`orderUpdateId` | `paused`/`succeeded`/`failed`/`cancelled`/`unknown` | `state.orderId` 匹配且 `driving`/`nodeStates` 有推进 | ✅ 但语义过宽 |
| `paused` | 车端 `paused=true` 或平台主动暂停 | `running`/`cancelled` | `State.paused` | ❌ 被折叠进 `running` |
| `unknown` | 心跳超时/查询连续失败 | `running`/`failed`（对账后） | 连接 `CONNECTION_BROKEN` | ❌ 缺（直接判 failed，或看门狗发告警） |
| `succeeded` / `failed` / `cancelled` | 终态 | — | `FINISHED`/`FAILED` | ✅（done/failed/cancelled） |

**三条硬规则**（建议写进代码注释 + 单测）：
1. **不允许跳态**：`planned→running` 非法（必须经 `queued→dispatched`）。现在 `cruise._run` 第一件事就是 `run.status = "running"`（[cruise.py:78](../../server/app/services/cruise.py#L78)），是跳态。
2. **`dispatched` 只能由"车端回显"推进**，不能由"HTTP 200"推进。X30 的 1003 是**长阻塞**接口（文档注明要等任务结束才返回，见 [adapter.py:140-146](../../server/app/adapters/deeprobotics/adapter.py#L140) 的注释），"发出去了"≠"受理了"。
3. **每态迁移写一条 `task_run_event`**（`run_id, seq, from, to, reason, at`），这是后面做对账、SLA、复盘的唯一依据。

### 2.5 幂等键（照抄 VDA5050）

| 层 | 键 | 生成规则 | 用途 |
|---|---|---|---|
| 订单 | `order_id` | `run-{run.id:08d}`（**一次性生成后入库，永不变**） | 重发同单不产生第二个车端任务 |
| 订单版本 | `order_update_id` | 从 0 单调 +1；每次改单（跳点/改序/补点）才 +1 | 车端拒单时把该值带回；平台据此判断"车端跑的是哪一版" |
| 节点 | `sequence_id` | 全局单调（node 与 edge 共用），单点巡航时可等于 `step.seq` | 断点续跑 `from_seq` 的锚 |
| 事件 | `(run_id, seq, to_status)` 唯一 | — | 状态回传重放 100 次结果不变 |

---

## 3. B. "到点"到底怎么判

### 3.1 行业做法对照

| 信号 | 来源/标准 | 判据（原文/默认值） | 我们有吗 |
|---|---|---|---|
| **坐标容差** | VDA5050 `nodePosition.allowedDeviationXY` | "=0 不允许偏差（意为在厂家正常容差内）；>0 为**允许的偏差半径（米）**，AGV 在该半径内通过即视为已穿越" | ✅ `PointDraft.arrive_radius_m`（默认 1.0，仪表点 0.3），且 FINISHED 后复核（[cruise.py:257-274](../../server/app/services/cruise.py#L257)） |
| **姿态容差** | `allowedDeviationTheta` | "theta ± 该值" | ❌ 完全没有 |
| **车端节点状态** | `nodeStates` 收缩 + `lastNodeId` 前移 | 节点从列表消失/被记为 last = REACHED | ⚠️ 只有 `1007 Status=0` 一个布尔（[adapter.py:158-162](../../server/app/adapters/deeprobotics/adapter.py#L158)） |
| **导航结束码** | Nav2 `NavigateToPose` result / `goal_checker` | 成功需满足 `xy_goal_tolerance` + `yaw_goal_tolerance` 且**速度收敛** | ⚠️ 我们只有 FINISHED/FAILED |
| **速度阈值** | Nav2 goal checker / 各家调度 | 到点瞬间速度模长 ≈ 0（典型阈值 0.05 m/s 量级），否则"报完成但还在滑行" | ❌ |
| **停留时间(dwell)** | 行业通行 + 巡检业务要求 | 停稳后保持 T（测温/拍照 0.5–3 s）才开始动作 | ❌（`wait` 动作是动作，不是到点判据） |
| **定位质量** | `agvPosition.localizationScore`（0=未知,1=已知）、`deviationRange`（米） | 位置是否可信；低分时应拒绝下发或不判到点 | ⚠️ X30 只给 `Location==1` 布尔（[adapter.py:69](../../server/app/adapters/deeprobotics/adapter.py#L69)） |

### 3.2 建议的"与门"判据（可直接实现）

```python
arrived = (dist <= r) and (abs(dyaw) <= yaw_tol) and (abs(v) <= 0.05)
          and (dwell_ok) and (car_state in ("FINISHED",))   # 车端确认
          and (loc_score is None or loc_score >= 0.5)        # 拿不到则不卡
```

| 点位类型 | `r`(m) | `yaw_tol`(rad) | dwell(s) | 说明 |
|---|---|---|---|---|
| 充电桩/对接位 | 0.15 | 0.10 | 2.0 | 误差直接导致对接失败 |
| 仪表/表计读数 | 0.30 | 0.20 | 1.5 | 需要朝向正对表盘 |
| 阀门/开关操作位 | 0.30 | 0.15 | 1.0 | 操作精度要求 |
| 门口/通道观察 | 0.50 | 0.40 | 0.5 | 只要"看得到" |
| 一般巡视点 | 1.00 | 0.60 | 0.5 | 现在就是 1.0 |

**定位漂移怎么处理（关键）**：不要二值化成"到了/没到"，而是三值：

| 判定 | 条件 | 平台动作 |
|---|---|---|
| `arrived` | 全部与门通过 | 执行点位动作，记 `deviation` |
| `arrived_suspect`（**新增**） | 车端 FINISHED 但 `dist > r` 且 `dist < 3r`，或 `loc_score < 0.5` | **动作照做但结果标记 `degraded=True`**，同时把该点加入"待重定位"队列；**不重试**（重试只会更偏） |
| `failed` | `dist >= 3r`，或车端 FAILED，或超时 | 标记失败原因"机器人报完成但离目标 X m"，触发重定位流程后再决定是否重试 |

> 现在代码是 `dist > radius` 直接判失败（[cruise.py:270](../../server/app/services/cruise.py#L270)）。这在"车已经到附近、只是 SLAM 漂了"的场景下会**误报失败并触发无意义重试**，运维看到的是"任务失败"而不是"该重定位了"。

---

## 4. C. 多机器人调度：防死锁、资源锁、异构落地

### 4.1 Open-RMF 的两层机制（照抄结论，不照抄实现）

**第一层：预防（Prevention）** —— 交通日程库。所有车队把**未来**轨迹登记进中央 schedule，planning 时直接避开。要点是"**意图公开**"：不是等撞上再躲，而是先声明"我 10 秒后要过这个路口"。

**第二层：协商（Negotiation）** —— 冲突发生后，`Negotiation` 建一张"表"：`Table` 是"某个参与者视角下、迁就某组参与者"的提案视图（`for_participant` 的 itinerary 被从表里剔除，`to_accommodate` 按层级依次迁就），各方提交偏好 itinerary，`ready()` = 存在"全体同意"的提案，`complete()` = 所有可能提案都到了，最后由注入的 `Evaluator`（如 `QuickestFinishEvaluator`）裁决。

**资源（门/电梯/充电桩）**：RMF 把它们做成路网 lane 上的**必经事件**（`LiftSessionBegin/LiftMove/DoorOpen/Dock`），而不是外挂一把锁——因为"占电梯"本质上就是"路径的一段被独占"。

**防死锁的隐性前提**（RMF 文档明说的）：车队的控制等级决定它能不能参与协同；`Read Only` 车队每个共享空间**最多一个**，`No Interface` 直接"会死锁"。→ **结论：能不能防死锁，先看你有多少控制权，而不是算法多聪明。**

### 4.2 我们的现实约束

| 约束 | 事实 |
|---|---|
| 没有路网/拓扑图 | 平台只有 `PointDraft(x,y,theta)`，没有 lane/站点容量 |
| 车端不可下发路径 | X30 只接目标点（1003），无法指定"走哪条路" |
| 暂停能力缺失 | JCROB `pause/resume` 直接 `NotSupported`（[http_adapter.py:238-242](../../server/app/adapters/jcrob/http_adapter.py#L238)）；X30 无暂停，只能 cancel 再重发 |
| 位置可读 | 两家都能读 `(x,y,yaw)`，这是唯一可靠的协同输入 |
| 并发上限 | 现场通常 1–3 台；`task_lock` 已保证"一车一任务" |

→ 我们**做不了 RMF 那种协商**（没有轨迹、没有暂停权、没有改单权），但**必须做的基础三件事**是：单机互斥、关键区互斥、等待可超时。

### 4.3 最小可用版设计（建议直接落地）

**表 1：`resource_lock`（新增，一表搞定所有资源）**

| 字段 | 说明 |
|---|---|
| `id` | PK |
| `kind` | `zone`（分区/走廊）/`door`（防火门）/`lift`（电梯）/`charger`（充电桩）/`dock`（停靠位）/`point`（独占点位，如操作位） |
| `key` | 资源标识，如 `charger-A`、`zone-2F-east`、`door-D3` |
| `capacity` | 默认 1；充电桩可按实际桩数配 |
| `holder_run_id` | 持有者（NULL = 空闲） |
| `holder_robot_id` | 冗余，便于排查 |
| `acquired_at` / `expires_at` | **必须有 TTL**（如 zone 300 s、lift 180 s、charger 7200 s） |
| `lease_token` | 续约令牌（心跳续租，避免"车还在里面但租约到期被抢"） |

**表 2：`cruise_step_resource`**：`(run_id, seq) → resource_key`，即"这个点位需要先拿哪些资源"。把"占资源"挂到 step 上，而不是散在业务代码里（这就是 RMF 把 lift 做成 lane event 的思路）。

**抢锁流程（一个函数，约 40 行）**

```
try_acquire(run, step):
  need = resources_of(step)                # 来自 cruise_step_resource
  for k in sorted(need):                   # 固定顺序，避免交叉等待（关键！）
      row = SELECT ... WHERE key=k FOR UPDATE
      if row.holder is not None and not expired(row):
          return BUSY(retry_after=row.expires_at - now)
      row.holder = run.id; row.expires_at = now + ttl(k); row.lease_token = uuid()
  return OK
```

- **固定获取顺序**（按 `key` 字典序）= 消灭"环路等待"这一必要条件，比任何环检测都便宜。
- **等待而非抢占**：`BUSY` 时把 run 放回 `queued` 并写 `waiting_on`，`retry_after` 到点再试。**只有 `admin` 角色能"抢占"**（等同于 RMF 的"紧急任务强制协商"），且必须写审计。
- **死锁兜底**：每 15 s 扫一次 `waiting_on` 有向图，发现环（A 等 B、B 等 C、C 等 A）→ 选"持锁时间最短/优先级最低"的持有者强制释放并发 `critical` 告警。这是兜底，不是主路径。
- **TTL 强拆**：持锁超过 TTL 自动释放 + 告警"任务 #x 持锁超时，可能车卡住了"。

### 4.4 "一个平台管 N 台不同厂商车"的落地策略

| 步骤 | 做法 | 为什么 |
|---|---|---|
| 1. 能力矩阵落到设备台账 | 每台车声明 `supports = {goto, whole_order, pause, resume, cancel, set_pose, read_pose, read_battery, capture}`，由 `probe_capabilities()` 实测填充（已有框架：[adapter.py:110](../../server/app/adapters/deeprobotics/adapter.py#L110)、[http_adapter.py:192](../../server/app/adapters/jcrob/http_adapter.py#L192)） | 现在 `registry.ADAPTERS` 的 `supported: bool` 太粗，导致"能整单的车被迫逐点跑" |
| 2. 执行模式由能力决定 | `exec_mode = whole_order if cap.whole_order else stepwise`；巡航执行器只认 `exec_mode`，不认厂商 | 消除"取交集"的技术债 |
| 3. 协同等级由能力决定 | `can_pause` 或 `can_cancel` → 可参与资源互斥；两者都无 → 标 `read_only`，**不参与锁，只上报位置避让** | 抄 RMF 的 "Read Only 车队最多一个" |
| 4. 统一异常语义 | 适配器把厂商错误码映射到 5 类：`LINK_LOST` / `NOT_ACCEPTED` / `NAV_FAILED` / `ESTOP` / `UNSUPPORTED` | 现在 `NotSupported` 与网络异常混在 `Exception` 里（[cruise.py:95-98](../../server/app/services/cruise.py#L95)） |

---

## 5. D. 定位与初始化：机器狗怎么"知道自己在哪"

### 5.1 定位链条（谁负责什么）

| 环节 | 作用 | 我们的现状 |
|---|---|---|
| **LiDAR SLAM 建图** | 产出 `map` 栅格 + 位姿图，**地图坐标系在此刻被钉死**；所有巡检点位坐标都是这张图的坐标 | 车端做（X30 在导航主机）；平台只有 `PlatformMap` 的底图 + `origin_*` 手工标定（[map_library.py:11-35](../../server/app/models/map_library.py#L11)） |
| **全局定位/重定位** | 在已知地图里求 `map→base_link`：AMCL（粒子滤波）/ scan-context / 厂家私有算法 | 车端做；接口是 X30 的 2101 `init_loc`（[adapter.py:175](../../server/app/adapters/deeprobotics/adapter.py#L175)） |
| **里程计（轮式/足式）+ IMU** | 提供 `odom→base_link`，短时高频、**长期必漂** | 车端，平台拿不到 |
| **TF 链** | `map→odom→base_link`；AMCL 只发布 `map→odom`，**修的是这个变换**，不是修里程计 | 车端 |
| **RTK / UWB（室外）** | 室外绝对定位，用来抑制定位漂移/做图根控制 | 未接 |
| **平台** | 只消费 `(x,y,yaw)` + 定位质量 + `map_id`，并**决定何时要求重定位** | 有 `init_location` 端点（[robots.py:94](../../server/app/api/v1/robots.py#L94)）但无策略 |

### 5.2 `/initialpose` 这类重定位，什么场景**必须**做

| 触发场景 | 物理原因 | 检测信号（我们能拿到的） | 必须做的事 |
|---|---|---|---|
| **断电/重启后首次上电** | 编码器/IMU 零点丢失，里程计从 0 开始 | 车端 `Location==0` / `positionInitialized=false` | 强制 `set_initial_pose` 到"最后已知位姿"或"停车位坐标"，**未成功前禁止下发任务** |
| **被搬动/抬升/装车** | 机器人物理位置变了但内部位姿没变 | 平台记录的最后位姿 vs 任务起点距离过大；或人工标记"已移动" | 强制重定位 + **人工确认**（自动值可能是错的） |
| **切换地图/换楼层** | 换图后坐标系变了 | `current_map != run.map_id` | 先 `set_initial_pose` 再到楼层基准点；这正是 VDA5050 用 `mapId` 标在每个节点上的原因 |
| **定位质量掉底** | 长走廊/空旷区/动态遮挡导致粒子发散 | `localizationScore` 低 / `deviationRange` 大 / 连续多帧位姿跳变 > 0.5 m | 暂停任务 → 全局重定位（Nav2 的 `ReinitializeGlobalLocalization` 就是干这个的）→ 校验通过再续跑 |
| **长时间停放后漂移超阈** | 里程计累积误差 | 上电后位姿与"上次结束位姿"差 > 阈值（如 0.5 m / 10°） | 以"上次结束位姿"为先验注入 |
| **维护/重建图之后** | 地图变了，旧先验全错 | `map.version` 变化 | 点位坐标迁移 + 全部强制重定位 |

> Nav2 侧对应关系：`/initialpose`（`PoseWithCovarianceStamped`，RViz 的 "2D Pose Estimate" 发的就是它）给先验；参数 `set_initial_pose`/`initial_pose` 可让节点启动即置位；完全不知道在哪时用"全局重定位"（`ReinitializeGlobalLocalization` 行为树插件）。见 [AMCL 配置](https://docs.nav2.org/lyrical/configuration_and_development/configuration_guide/others/configuring_amcl/)、[ReinitializeGlobalLocalization](https://docs.nav2.org/lyrical/configuration_and_development/configuration_guide/core_servers/bt_plugins/actions/ReinitializeGlobalLocalization/)。

### 5.3 建图与"固定点位坐标"的关系（最容易出事的地方）

- 点位坐标**只在它被采集的那张地图里有意义**。重建图 = 换了一个坐标系 = **所有点位静默失效**。
- VDA5050 的处理方式值得抄：每个 `nodePosition` 都带 `mapId`，且规定"**每层楼一张图，各图原点一致**"，跨层时 AGV"从出发层地图消失、在目标层电梯节点出现"。
- 我们要补的字段（`PlatformMap` / `PointDraft`）：

| 字段 | 表 | 作用 |
|---|---|---|
| `map.version` | `platform_map` | 每次重建图 +1；点位绑版本 |
| `map.frame_id`（如 `map_2f_v3`） | `platform_map` | 与车端 `map_id` 对齐，作为下发/校验依据 |
| `point.map_version` | `point_draft` | 防"图换了点位还在" |
| `point.map_id` | `point_draft` | 现在 `map_id` 有，但没参与下发校验 |
| `point.last_verified_at` | `point_draft` | 上次现场实测该点误差的时间 |

**点位迁移流程（重建图后的标准动作）**：新图建好 → 在"已知物理位置"（如充电桩、门口）标 3 个以上同名控制点 → 求新旧图刚体变换（2D 相似变换：平移+旋转+尺度）→ 批量变换点位 → **人工抽检 10%** → 置 `last_verified_at`。没有这个流程，重建图就是灾难。

### 5.4 odom 漂移 / 坐标系错位：手工标定 vs 自动重定位

| 手段 | 解决什么 | 成本 | 成熟度 | 我们该不该做 |
|---|---|---|---|---|
| **手工标定**（图上点两点定比例尺+原点+旋转） | 底图与车端地图的**静态**错位 | 低（已有 `origin_x/y/theta`、`resolution`） | 高 | ✅ 已有，保留为兜底 |
| **现场实测校正**（开到已知点，读位姿，算偏差，整体平移/旋转点位） | **静态**系统性偏差（如建图原点偏 0.3 m） | 中 | 高 | ✅ 强烈建议（一次性、可复现、可审计） |
| **任务中自动重定位**（到点前用 scan match 修正先验） | **动态**漂移 | 中 | 高（AMCL 本来就在做） | ✅ 车端责任，平台只要求"到点前必须收敛" |
| **运行数据自标定**（用长期运行数据在线校正参数） | 长期参数退化（轮径、标定老化） | 高 | 商用有（国自"AGV 自标定"） | ⏳ 二期；先把"每次任务记录 deviation"的数据攒起来 |
| **RTK / 反光柱 / 二维码地标** | 绝对基准 | 高（施工） | 高 | ⏳ 室外/大场地再上 |

**关键认知**：坐标系错位有两种，必须分开治——
- **静态错位**（图与图、图与点位）：靠"控制点 + 刚体变换"一次性解决，写进点位库版本。
- **动态漂移**（运行中位姿漂）：靠车端重定位 + 平台的"到点存疑"判定 + 重定位触发器，不能靠改点位坐标（那是拿错位当噪声抹平，越抹越乱）。

---

## 6. E. 失败与恢复：中断、断网、低电、急停、续跑

### 6.1 失败矩阵（建议直接做成代码里的表）

| 故障 | 检测信号（现有/应加） | 自动动作 | 人工动作 | 幂等键 |
|---|---|---|---|---|
| **断网/车失联** | `get_order()` 连续失败（现在直接判失败，见 [cruise.py:253-255](../../server/app/services/cruise.py#L253)） | 进入 `unknown`，**不发新指令**（防止"网回来了两条指令打架"），指数退避重连 | 确认车在哪、是否需现场干预 | `order_id` 不变 |
| **任务中断（进程重启）** | 启动时扫残留 `running`（[main.py:72](../../server/app/main.py#L72) 现在是直接标 failed） | 标 `unknown` → 对账（读车端 `orderId`）→ 一致则**恢复跟踪**，不一致则 failed | 选择"续跑/放弃" | `order_id`+`from_seq` |
| **电量不足（任务中）** | 周期读 `battery`（现在只在 preflight 查一次，阈值 30%，[task_dispatch.py:66](../../server/app/services/task_dispatch.py#L66)） | `<20%`：做完当前点 → 中止剩余点 → 插 `ChargeBattery` → 充满后**从 `from_seq` 续跑**（RMF 的 ChargeBattery 自动注入就是这个语义） | 确认能否回充 | `run_id`+`resume_seq` |
| **急停** | 状态字含"急停"/`estop`（[task_dispatch.py:92](../../server/app/services/task_dispatch.py#L92)） | 立即停发；任务置 `paused` 而非 failed；**急停期间禁止任何写操作** | 现场解除 → 平台 resume（要求先校验位姿） | `order_id` 不变 |
| **定位丢失/漂移** | `Location==0` / `loc_score` 低 / 到点偏离 | 停止下发 → 触发重定位 → 校验（走 1 m 看位姿自洽）→ resume | 必要时人工给先验 | 同上 |
| **点位不可达** | 车端 FAILED / 超时 | 跳过该点继续（可配置策略：跳过 or 中止整单），**记录到报告** | 决定是否重规划 | `(run_id, seq)` 唯一 |
| **动作失败（拍照/测温）** | 适配器异常（[cruise.py:113-120](../../server/app/services/cruise.py#L113)） | 重试 ≤2（间隔 3 s/10 s），仍失败则标 `degraded` 继续 | 补拍 | `(run_id, seq, action) ` 唯一 |
| **人工接管（遥控）** | 操作员点"接管" | 平台释放机器人锁、任务 `paused`；**记录接管开始位姿** | 接管结束后选择"续跑/放弃" | RMF 的 `interrupt→Resume` 语义 |

### 6.2 "续跑"要解决的三件事（我们现在只做了一件）

| 事项 | 现在 | 应该 |
|---|---|---|
| 从哪继续 | `start_cruise(from_seq=...)` 手工传（[task_runs.py:303](../../server/app/api/v1/task_runs.py#L303)） | 自动：取 `min(seq where status != ok)`，且校验"车当前位姿 ≈ 该点或上一点"（否则先导航到上一点再续） |
| 已做过的不重复 | 重跑时**清空所有 step 结果**（[task_runs.py:336-341](../../server/app/api/v1/task_runs.py#L336)） | 只清 `from_seq` 之后的；已 `ok` 的保留（否则审计断链、照片重拍） |
| 车端还在跑旧单怎么办 | 无对账 | 续跑前读车端 `state.orderId`；若等于旧 `order_id` → 先 cancel 再发新单；若不等于 → 说明车端已被别人用，**禁止下发** |

### 6.3 RMF 给的三档"停"，值得照抄语义

| RMF | 语义 | 我们对应 |
|---|---|---|
| `cancel()` | 优雅停止：不再推进任务，但允许做完必要的收尾 phase（回停车位/关门） | `cancel` + 一条"回停靠点"的收尾 step（现在没有） |
| `kill()` | 立刻回安全态，不保证收尾 | 急停 / 人工强制中止 |
| `interrupt(cb) → Resume` | 临时让出机器人（人工接管、消防联动），**给出恢复凭据** | `paused` 需要一个 `resume_token` + "接管期间位姿记录"，现在只有一个 `paused_at` 时间戳 |

---

## 7. F. 给我们这套系统的最小改造清单（8 条，按优先级）

> 排序依据：**先修"会静默出错"的（状态机/幂等/到点判定），再修"会卡住整个系统"的（资源锁/定位），最后补"可运营"的（续跑/观测）**。每条都给了验收方法，能直接写进测试。

### P0-1 订单模型：`order_id` 稳定化 + `order_update_id` + 能力驱动的 `exec_mode`

- **改哪**：`server/app/services/task_dispatch.py`（`_order_payload` / `dispatch`）、`server/app/models/task_run.py`（加 `order_update_id`、`exec_mode`）、各适配器 `dispatch()`。
- **为什么**：现在 `orderId = JC-{毫秒}` 每次调用都变（[task_dispatch.py:123](../../server/app/services/task_dispatch.py#L123)），重发即新车端任务，**没有幂等底座**；且整单/逐点写死在巡航器里，能整单的 JCROB 被迫逐点跑。
- **怎么做**：`order_id = f"run-{run.id:08d}"` 入库不变；改单才 `order_update_id += 1`；适配器声明 `exec_mode`，`X30` 只能 `stepwise`，`JCROB` 可 `whole_order`。
- **验收**：①同一 run 连续调两次 dispatch，车端只出现一个任务（第二次被"同 orderId+同 updateId"拒绝或幂等返回）；②X30 走 stepwise、JCROB 走 whole_order，`order_json` 里 `exec_mode` 与台账能力一致；③单测覆盖"改单 → updateId+1 → 车端旧单一律 cancel"。

### P0-2 状态机 5 态 → 8 态，禁止跳态，每次迁移落事件

- **改哪**：`server/app/models/task_run.py`、`server/app/services/{task_dispatch,cruise}.py`、`server/app/api/v1/task_runs.py`；新增 `task_run_event` 表。
- **为什么**：`planned→running` 跳态（[cruise.py:78](../../server/app/services/cruise.py#L78)），`PAUSED` 被折叠进 `running`，缺 `dispatched`/`unknown`，导致"发出去了"与"车受理了"无法区分，看门狗只能靠 30 s 无进度猜。
- **验收**：①非法迁移一律 409 且不写库；②拔网线 60 s：run 进 `unknown` 而**不是** failed，恢复后自动回 `running`；③每次迁移在 `task_run_event` 有一条记录，能按时间轴还原一次任务。

### P0-3 到点判定升级为"与门 + 三值"，新增 `arrived_suspect`

- **改哪**：`server/app/services/cruise.py::_wait_arrival`；`PointDraft` 加 `yaw_tol`、`dwell_s`；适配器补 `get_velocity()`/`get_loc_score()`（拿不到返回 None）。
- **为什么**：现在只有"FINISHED + 距离"（[cruise.py:257-274](../../server/app/services/cruise.py#L257)），缺速度/角度/停留/定位质量；且超容差直接判 failed，把"该重定位"误报成"任务失败"。
- **验收**：①mock 注入 `dist=0.8m, FINISHED, loc_score=0.3` → 判 `arrived_suspect`、动作照做但 `degraded=True`、**不重试**、进重定位队列；②`dist=0.1m` 但速度 0.3 m/s → 不判到点，等停稳；③仪表点（0.3 m/0.2 rad）与巡视点（1.0 m/0.6 rad）参数生效。

### P1-4 资源锁表 + 固定顺序抢锁 + TTL 回收 + 环检测

- **改哪**：新增 `server/app/services/resource_lock.py`、`resource_lock`/`cruise_step_resource` 两张表、`map_library` 点位加 `resources` 字段。
- **为什么**：现场多机（含充电桩/防火门/窄通道）没有互斥，靠人工排班；RMF 的结论是"不能协同的车队必然死锁"，我们没有暂停/改道权，**只能靠预约**。
- **验收**：①两车同一充电桩：第二车 `BUSY` 进 `queued` 并显示 `waiting_on=charger-A`，不并行下发；②按 key 字典序抢锁，构造"A 要 X,Y / B 要 Y,X"用例，**不产生死锁**；③持锁超 TTL 自动释放并告警；④环检测能在一个调度周期内发现并拆环。

### P1-5 定位初始化策略化：触发器 + 初始化后校验 + 未就绪禁止下发

- **改哪**：`server/app/services/` 新增 `localization.py`；复用 `robots.py::init_location`（[robots.py:94](../../server/app/api/v1/robots.py#L94)）与适配器 `set_initial_pose`；`preflight` 增加"定位就绪"检查。
- **为什么**：初始化现在只有一个手工按钮，没有"什么时候必须做"和"做完对不对"。断电报废、被搬动、切图这三类事件不做，导航必跑偏。
- **验收**：①`Location==0` 时下发被 `PREFLIGHT_FAILED` 拦住并提示"需重定位"；②初始化后自动走 1 m 校验，位姿不自洽 → 判初始化失败、不进 `running`；③切图（`map_id` 变化）自动触发初始化并记录审计；④单测覆盖 5 类触发器。

### P1-6 幂等与去重：唯一约束 + 事件去重 + 状态回传重放安全

- **改哪**：`task_run.external_id` / `(run_id, seq)` 加唯一约束（`alembic` 新版本）；`task_run_event` 加 `(run_id, seq, to_status)` 唯一；状态回传按 `(orderId, orderUpdateId, seq)` 去重。
- **为什么**：现在 `external_id` 只有普通索引（[task_run.py:37](../../server/app/models/task_run.py#L37)），重复上报会产生两条；车端/网关重传是常态。
- **验收**：①同一条状态回传重放 100 次，`task_run` 只有一行、事件只有一条；②并发两次 dispatch 只成功一次（第二个 409）；③迁移脚本在存量数据上可重复执行（幂等迁移）。

### P2-7 失败恢复三件套：断点续跑 + 低电让位 + 人工接管

- **改哪**：`cruise.py`（`from_seq` 自动推导 + 车端订单对账）、`task_dispatch.py`（低电让位、`resume_token`）、`task_runs.py`（续跑/接管端点）。
- **为什么**：`from_seq` 现在是手工传且重跑清空所有结果（[task_runs.py:336-341](../../server/app/api/v1/task_runs.py#L336)）；低电只在 preflight 查一次；接管只有一个 `paused_at`。
- **验收**：①跑到第 7 点拔网 30 s → 恢复后从第 7 点续跑，第 1-6 点结果与照片**不被清空/重拍**；②电量掉到 18% → 做完当前点、回充、充满从断点续跑；③接管→释放后 resume 要求"位姿校验通过"，否则拒绝并要求重新定位。

### P2-8 观测：每步记录"计划 vs 实际"，把差距变成可查的数字

- **改哪**：`task_run_step.result_json` 增加 `planned{x,y,yaw}`、`actual{x,y,yaw}`、`deviation_m`、`arrive_elapsed_s`、`retries`、`relocalized`；`api/v1/metrics.py` 暴露"到点偏差 P50/P95""重定位次数/任务""单点超时率"。
- **为什么**：没有 deviation 数据，就无法判断"是不是该重建图/该重标定"，只能凭感觉；这也是厂商"自标定"的数据前提。
- **验收**：①一份 20 点巡航报告能定位到"哪一步、差多少米、是否重定位过"；②连续 7 天 deviation P95 > 1.0 m 时，系统给出"建议重标定/重建图"提示；③这些指标进 `/metrics`，能被看板消费。

---

## 8. "我们 vs 成熟方案"差距表

| # | 维度 | 我们现在 | 成熟方案（RMF / VDA5050 / Nav2） | 差距等级 | 补救 |
|---|---|---|---|---|---|
| 1 | 任务下发粒度 | 逐点 `goto` + 3 s 轮询（X30 能力所限，被迫拉平 JCROB） | 整单 + base/horizon，车端自主执行；或 `NavigateThroughPoses` | 🔴 高 | P0-1 |
| 2 | 订单幂等 | `orderId` 每次新生成，`external_id` 无唯一约束 | `orderId`+`orderUpdateId` 单调、拒单回传该字段 | 🔴 高 | P0-1 / P1-6 |
| 3 | 状态机 | 5 态，无 `dispatched`/`unknown`，pause 折叠进 running，存在跳态 | `dispatched→running→paused/unknown` 全显式，逐 phase 进度 | 🔴 高 | P0-2 |
| 4 | 到点判定 | FINISHED + 距离复核（单信号） | 坐标+姿态容差+速度+dwell+节点 REACHED+定位质量 | 🟠 中高 | P0-3 |
| 5 | 漂移处理 | 超容差 → 直接 failed → 盲重试 | 定位质量分级、低分拒判、触发全局重定位 | 🟠 中高 | P0-3 / P1-5 |
| 6 | 多机冲突 | 一车一任务（`task_lock` 查前检查），无资源/分区互斥 | 日程库 + 协商 + 门/梯/桩作为路径资源 + TTL | 🔴 高 | P1-4 |
| 7 | 定位初始化 | 手工按钮，无触发器、无校验、无"未就绪禁下发" | `set_initial_pose`/`/initialpose`/全局重定位 + 生命周期就绪门 | 🟠 中高 | P1-5 |
| 8 | 地图/楼层/点位版本 | `floor`+`origin_*` 有，但点位不绑地图版本，重建图即静默失效 | `mapId` 逐节点标注，每层一图、原点一致；切图是显式动作（连 free_fleet 都还没做） | 🟠 中高 | P1-5 附带（本次不展开实现） |
| 9 | 断点续跑 | `from_seq` 手工传，重跑清空全部 step 结果 | `lastNodeId` 自动续跑；checkpoint(`backup`)；`Resume` 凭据 | 🟠 中高 | P2-7 |
| 10 | 巡检抽象 | "task_run + step + point"，语义偏"工单" | "places 列表 + 循环次数 + 到点动作"（`dispatch_patrol`） | 🟢 低 | 已有，命名对齐即可 |

> 一句话总结差距：**我们不缺"发指令"，缺的是"任务作为一等实体"**——可幂等、可续跑、可改单、可裁决、可观测。上面 8 条改造里，P0 三条全部围绕这一点。

---

## 9. 参考链接汇总

**Open-RMF**
- RMF Core Overview（车队分级、日程库、协商）https://osrf.github.io/ros2multirobotbook/rmf-core.html
- Tasks in RMF（bidding、ChargeBattery 注入、`is_charger`）https://osrf.github.io/ros2multirobotbook/task.html
- Mobile Robot Fleet Integration（`RobotCommandHandle` 必须实现的回调）https://osrf.github.io/ros2multirobotbook/integration_fleets.html
- `rmf_task::Task` API（backup / interrupt / Resume / cancel / kill）https://docs.ros.org/en/ros2_packages/rolling/api/rmf_task/generated/classrmf__task_1_1Task.html
- `rmf_traffic::schedule::Negotiation` API（Table/ready/complete/Evaluator）https://openrmf.readthedocs.io/projects/rmf-traffic/en/latest/api/classrmf__traffic_1_1schedule_1_1Negotiation.html
- `Lane::LiftMove` / `DoorOpen` 等资源事件 https://openrmf.readthedocs.io/projects/rmf-traffic/en/latest/api/classrmf__traffic_1_1agv_1_1Graph_1_1Lane_1_1LiftMove.html
- `rmf_demos_tasks`（`dispatch_patrol`：地点列表 + 循环次数 + cancel）https://docs.ros.org/en/ros2_packages/rolling/api/rmf_demos_tasks/README.html
- free_fleet（RMF adapter 的 Python 实现，TODO 里含 "map switching support"）https://github.com/open-rmf/free_fleet
- fleet_adapter_template（`navigate/stop/execute_action/position/battery_soc` 回调清单）https://github.com/open-rmf/fleet_adapter_template

**VDA5050**
- 规范 v2.0 英文 PDF https://www.vda.de/dam/jcr:f0c9c019-1506-4dee-998a-e92723fbf025/EN-VDA5050-V200.pdf
- 规范 Markdown（2.1.0）https://github.com/VDA5050/VDA5050/blob/2.1.0/VDA5050_EN.md
- 字段级参考（注释摘自规范）：Order https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/order/struct.Order.html ｜ NodePosition https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/common/struct.NodePosition.html ｜ State https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/state/struct.State.html ｜ AgvPosition https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/common/struct.AgvPosition.html ｜ Action https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/action/struct.Action.html ｜ InstantActions https://docs.rs/vda5050-types/latest/vda5050_types/v2_0/instant_actions/struct.InstantActions.html

**ROS2 Nav2**
- 配置总览（版本化目录）https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/
- Waypoint Follower（`FollowWaypoints` 逐点执行）https://docs.nav2.org/rolling/configuration_and_development/configuration_guide/core_servers/waypoint_follower/
- BT Navigator（行为树 XML 编排）https://docs.nav2.org/rolling/configuration_and_development/configuration_guide/core_servers/configuring_bt_navigator/
- `NavigateThroughPoses` 默认行为树 https://docs.nav2.org/behavior_trees/trees/nav_through_poses_recovery.html
- AMCL 配置（`/initialpose`、`set_initial_pose`）https://docs.nav2.org/lyrical/configuration_and_development/configuration_guide/others/configuring_amcl/
- `ReinitializeGlobalLocalization` 行为树插件（全局重定位）https://docs.nav2.org/lyrical/configuration_and_development/configuration_guide/core_servers/bt_plugins/actions/ReinitializeGlobalLocalization/
- `nav2_amcl` 源码说明 https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/README.md

**巡检/多机开源项目**
- ros2_patrol_robot（ROS2 + Nav2 巡检仿真）https://github.com/ruali-dev/ros2_patrol_robot
- PlanSys2 巡逻示例（PDDL 规划巡逻序列 + FSM 控制）https://github.com/IntelligentRoboticsLabs/ros2_planning_system_examples/tree/master/plansys2_patrol_navigation_example
- 巡逻教程正文 https://raw.githubusercontent.com/PlanSys2/ros2_planning_system/d3b466f7126833c7db6fcf559c0bc4c0fe0434be/plansys2_docs/tutorials/tut_2_patrol.md

**商用（公开资料）**
- 国自 GRACE Xpress 2.0（2000+ 台/1 s 派单、10 万㎡交通、AGV 自标定）https://www.zidonghua.com.cn/news/newproduct/61708.html
- 国自 太重项目（近 200 台异构机器人混行）https://www.gzrobot.com/news/708275604058181/708986583388229
- 亿嘉和（"站端+集控"、"云—边—端"多机协同）http://stock.10jqka.com.cn/20260827/c679346996.shtml
- 申昊 × 优必选（电力巡检生态合作）https://www.gkzhan.com/news/detail/193138.html

> 商用四家的公开材料里，**只有国自给出了可量化的调度/交通/标定指标**；申昊、亿嘉和、优必选的材料停留在"多机协同/云边端"的架构口号层面，无法提取可对标的实现细节——这一点在对外汇报时应当如实说明，不要把它们写成"技术标杆"。
