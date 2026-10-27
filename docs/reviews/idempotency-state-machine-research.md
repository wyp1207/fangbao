# 任务订单幂等 + 任务状态机：开源实现核实与最小改造方案

> 核实日期：2026-10-27（Asia/Shanghai）。技术栈限定：FastAPI + SQLAlchemy 2.0 + MySQL/SQLite。
> 方法：直接读 GitHub 文件（raw + jsDelivr 文件树 + ghproxy 镜像），只写实际读到的内容；读不到就标注“不可达”，不凭印象补。
> 本文不写业务代码，代码块是**数据结构、判定顺序、SQL/Alembic 片段**，可直接照抄语义，不直接粘贴成服务实现。

---

## 0. 结论先行

| # | 结论 | 证据 |
|---|---|---|
| 1 | VDA5050 **没有 order 级 status 枚举**。订单是否还在跑，由 `orderId/orderUpdateId + nodeStates/edgeStates/actionStates + paused + errors` 共同表达 | `OrderState.msg`、`vda5050_controller.py` |
| 2 | VDA5050 的幂等单元是 **`(orderId, orderUpdateId)`**：同单同版丢弃；低版拒绝；base 对不上拒绝；有活动单时换 `orderId` 拒绝 | `process_order()`、`OrderCallback()` |
| 3 | RMF 把“派发状态”（5 个）和“执行状态”（12 个）**分开建模**；pause 是 `interruption`，不是主状态 | `DispatchState.hpp`、`task_state.py`、`Event.hpp` |
| 4 | Nav2 的 `ACCEPTED/EXECUTING/CANCELING` 是 **action 传输态**，没有 `paused`；暂停 = 取消当前目标，平台不再发下一个点 | `GoalStatus.msg`、`BtActionServer::executeCallback` |
| 5 | 我们**5 个主态够用**；缺的是正交字段：`dispatch_state`、`paused_at`、`cancel_requested_at`、`last_seq`。不要扩成 8 态主枚举 | 下文 §5.3 |
| 6 | 幂等键不要用 UUID 当业务键。用 `order_id = JC-R{run_id:06d}-A{attempt:02d}` + `order_update_id`，可读、可对账、可重放 | 下文 §5.4 |
| 7 | 数据库层用“唯一索引 + 条件 UPDATE 抢占 + step upsert”，不靠“先查再写” | 下文 §4.2、§5.2 |
| 8 | 历史数据不用改 `status`；新列可空/带默认值，回填后建唯一索引；迁移可重复执行 | 下文 §5.5 |

---

## 1. 核实范围：哪些仓库真的存在、真的读到了

| 任务给的仓库 | 2026-10-27 实况 | 本文实际使用的证据 | 证据强度 |
|---|---|---|---|
| `ipa320/vda5050_connector` | **raw 404**（`master`、`main`、`current_ros_noetic`、`humble`、`rolling`、`foxy`、`ros2` 均 404）；jsDelivr 也取不到版本 | 不直接引用；改用另一份可读的 ROS1 `order_daemon` 实现 `tum-fml/vda5050_connector@current_ros_noetic`，并在文中注明“无法确认 fork 关系” | C（替代） |
| `vda5050/vda5050_connector` | **404**；VDA5050 官方组织下是规范仓库 `VDA5050/VDA5050`，没有这个 connector | 规范正文 + 两个真实 connector 实现 | C（不存在） |
| `open-rmf/free_fleet` | 存在，但**不是 VDA5050**：它是 Open-RMF 的 Python Fleet Adapter，走 Nav2 action / zenoh；没有 `orderId/orderUpdateId` | 只用于“谁推进状态”的对照，不用于订单幂等 | A |
| `inorbit-ai/ros_amr_interop` | 存在，`galactic-devel` 分支，VDA5050 v2 connector | `vda5050_connector/vda5050_connector/vda5050_controller.py`、`vda5050_msgs/msg/*.msg` | A |
| `open-rmf/rmf_task` / `rmf_ros2` / `rmf-web` | 存在，`main` 分支 | `DispatchState.hpp`、`Dispatcher.cpp`、`Event.hpp`、`task_state.py`、`repositories/tasks.py` | A |
| `open-rmf/rmf_demos` | 存在，`main` 分支；是 demo launch + `rmf_demos_tasks` 脚本，README 解释了 bidding 流程，但**不含状态机实现** | 只用来确认“任务派发是 bidding + DispatchCommand”，不把它当状态机代码 | B |
| `ros-navigation/navigation2` | 存在，`main` 分支（旧地址 `ros-planning/navigation2` 仍可重定向） | `nav2_msgs/action/*.action`、`bt_action_server_impl.hpp` | A |
| `NVIDIA-ISAAC/isaac_mission_dispatch` | 存在，`main` 分支；VDA5050 3.0 的 Mission Dispatch（Postgres + MQTT） | README 的 mission state、取消/删除、`pause_order` 语义；**未读源码，只作行为佐证** | B |

> 说明：`ipa320` 的 404 不等于“仓库被删除”，只说明当前公开 raw 不可达；本文不把不可达仓库当证据。
> 所有 GitHub 链接都指向分支，不指向 commit；核实日期之后可能变化。

---

## 2. VDA5050：数据结构与幂等校验到底写在哪

### 2.1 数据结构：订单、节点、状态

**订单头**（[`vda5050_msgs/msg/Order.msg`](https://github.com/inorbit-ai/ros_amr_interop/blob/galactic-devel/vda5050_msgs/msg/Order.msg)）：

```text
string order_id          # Unique order identification
uint32 order_update_id   # unique per order_id; 拒绝时要把该值带回
vda5050_msgs/Node[] nodes
vda5050_msgs/Edge[] edges
```

**节点**（[`vda5050_msgs/msg/Node.msg`](https://github.com/inorbit-ai/ros_amr_interop/blob/galactic-devel/vda5050_msgs/msg/Node.msg)）：

```text
string node_id
uint32 sequence_id    # 跨 node/edge 统一单调；新 order_id 时归零
bool released         # true=base（已承诺）；false=horizon（可被新单替换）
vda5050_msgs/NodePosition node_position
vda5050_msgs/Action[] actions
```

**车端状态**（[`vda5050_msgs/msg/OrderState.msg`](https://github.com/inorbit-ai/ros_amr_interop/blob/galactic-devel/vda5050_msgs/msg/OrderState.msg)）：

```text
string order_id
uint32 order_update_id
string last_node_id             # 最后到达/当前所在节点
uint32 last_node_sequence_id    # 对应的 sequence_id
vda5050_msgs/NodeState[] node_states   # 只列还没走完的
vda5050_msgs/EdgeState[] edge_states   # 只列还没走完的
bool paused                     # 车端暂停标志（物理按钮或 instantAction）
bool new_base_requested         # 快到 base 末尾，请补发新 base
vda5050_msgs/CurrentAction[] action_states  # WAITING/INITIALIZING/RUNNING/PAUSED/FINISHED/FAILED
vda5050_msgs/Error[] errors
```

**对照到我们表**：

| VDA 字段 | 含义 | 我们的落点 | 备注 |
|---|---|---|---|
| `order_id` | 逻辑订单号 | `task_run.order_id` | 一次生成，重发不变 |
| `order_update_id` | 同一订单的版本号 | `task_run.order_update_id` | 只有“改单”才 +1 |
| `nodes[].sequence_id` | 节点/边统一序号 | `task_run_step.seq` | 逐点巡航可直接复用 `seq` |
| `last_node_id` / `last_node_sequence_id` | 断点锚 | `task_run.last_seq` + step 状态 | 重启后续跑的依据 |
| `paused` | 车端暂停 | `task_run.paused_at` | 不新增主状态 |
| `new_base_requested` | 需要补发 base | 本期不用 | 逐点下发没有 base/horizon |
| `action_states[].action_status` | 动作状态 | `task_run_step.status` | 我们只有 pending/ok/failed/skipped，够用 |

### 2.2 inorbit 的幂等判定（Python，逐行可读）

文件：[`vda5050_connector/vda5050_connector/vda5050_controller.py`](https://github.com/inorbit-ai/ros_amr_interop/blob/galactic-devel/vda5050_connector/vda5050_connector/vda5050_controller.py#L837-L912)

```python
def process_order(self, order: VDAOrder):
    # 1) 先做消息校验；当前实现是 TODO，直接 return True
    msg_is_valid, error = self.order_msg_is_valid(order)
    if not msg_is_valid:
        self._reject_order(order, OrderRejectErrors.VALIDATION_ERROR, ...)
        return

    has_current_order = self._has_current_order()

    if order.order_id != self._current_order.order_id:
        # 2) 新 orderId：只要还有活动单，或首节点不在容差内，就拒绝
        if not self._first_node_in_deviation_range(order) or has_current_order:
            reject_error = ORDER_UPDATE_ERROR if has_current_order else NO_ROUTE_ERROR
        else:
            accept_mode = OrderAcceptModes.NEW
    else:
        # 3) 同 orderId：比 order_update_id
        update_id_diff = order.order_update_id - self._current_order.order_update_id
        match_last_new_base_nodes = self._match_base_nodes(order)

        if update_id_diff == 0:
            # 同单同版：直接丢弃，不回错误
            self.logger.info(f"Order [{order.order_id}] discarded. Same order update id.")
            return
        elif update_id_diff < 0 or not match_last_new_base_nodes:
            # 低版或 base 对不上：拒绝，并把 orderId/orderUpdateId 放进 error reference
            reject_error = OrderRejectErrors.ORDER_UPDATE_ERROR
        else:
            # 高版：有活动单走 STITCH，没有走 UPDATE
            accept_mode = OrderAcceptModes.STITCH if has_current_order else OrderAcceptModes.UPDATE

    if reject_error:
        self._reject_order(order, reject_error, error_description)
    else:
        self._accept_order(order, accept_mode)
```

关键点：

| 场景 | 行为 | 依据 |
|---|---|---|
| 同 `orderId` + 同 `orderUpdateId` | **丢弃**，不报错、不重发 | `update_id_diff == 0` |
| 同 `orderId` + 低 `orderUpdateId` | **拒绝**，错误里带 `order_id` / `order_update_id` | `update_id_diff < 0` |
| 同 `orderId` + 高 `orderUpdateId`，base 首节点对不上 | **拒绝** | `not match_last_new_base_nodes` |
| 同 `orderId` + 高 `orderUpdateId`，有活动单 | **STITCH**：清 horizon，保留 base，追加新节点 | `_accept_order` |
| 同 `orderId` + 高 `orderUpdateId`，无活动单 | **UPDATE**：替换当前订单 | `_accept_order` |
| 不同 `orderId`，但有活动单 | **拒绝** `orderUpdateError` | `has_current_order` |
| 不同 `orderId`，无活动单，首节点在容差内 | **NEW** | `_first_node_in_deviation_range` |

`_accept_order` 的 STITCH 核心（同文件 `#L996-L1080`）：

```python
if mode == OrderAcceptModes.STITCH:
    # 清掉当前订单里未 released 的 horizon
    self._current_state.node_states = [
        ns for ns in self._current_state.node_states
        if ns.released and ns.sequenceId != order.nodes[0].sequenceId
    ]
    self._current_state.edge_states = [
        es for es in self._current_state.edge_states if es.released
    ]
    # 只追加新 base 的 released 部分 + 新 horizon
    base_order_nodes = [
        n for n in order.nodes
        if n.released and n.sequenceId != order.nodes[0].sequenceId
    ]
    base_order_edges = [e for e in order.edges if e.released]
    self._current_order.order_update_id = order.order_update_id
    self._current_order.nodes = base_order_nodes + order.nodes
    self._current_order.edges = base_order_edges + order.edges
else:
    if mode == OrderAcceptModes.NEW:
        self._delete_action_states()
    self._current_order = order
```

**必须说明的坑**：这段代码不是“生产级范本”。同一文件里有拼写/字段错误（`nodes_states`、`sequenceId`、`currentOrders.front()` 等），`order_msg_is_valid()` 和 `_match_base_nodes()` 还是 `TODO` 直接 `return True`。**抄它的判定顺序，不要逐字抄实现**。

### 2.3 ipa320 的 ROS1 实现：可读替代 `order_daemon.cpp`

可读证据：[`tum-fml/vda5050_connector@current_ros_noetic/src/order_daemon.cpp`](https://github.com/tum-fml/vda5050_connector/blob/current_ros_noetic/src/order_daemon.cpp)（版权头是 TUM FML）。**无法确认它和 ipa320 的 fork 关系**；本文只把它当作“同代 ROS1 `order_daemon` 实现”的可读样本，不主张它等同于 ipa320。

`OrderCallback` 的判定骨架：

```cpp
if (currentOrders.back().compareOrderId(msg->orderId)) {
  if (compareOrderUpdateId(msg->orderUpdateId) == "LOWER") {
    orderUpdateError(msg->orderId, msg->orderUpdateId);
  } else if (compareOrderUpdateId(msg->orderUpdateId) == "EQUAL") {
    ROS_WARN_STREAM("Order discarded. Strucure invalid! " << ...);
  } else {
    if (compareBase(msg->nodes.front().nodeId, msg->nodes.front().sequenceId))
      updateExistingOrder(msg);
    else
      orderUpdateError(msg->orderId, msg->orderUpdateId);
  }
} else {
  if (compareBase(msg->nodes.front().nodeId, msg->nodes.front().sequenceId))
    appendNewOrder(msg);
  else
    orderUpdateError(msg->orderId, msg->orderUpdateId);
}
```

`CurrentOrder::compareOrderUpdateId` 的返回值只有三档，直接对应 VDA 语义：

```cpp
string CurrentOrder::compareOrderUpdateId(int orderUpdateIdToCompare)
{
    if (orderUpdateIdToCompare == this->orderUpdateId) return "EQUAL";
    else if (orderUpdateIdToCompare > this->orderUpdateId) return "HIGHER";
    else if (orderUpdateIdToCompare < this->orderUpdateId) return "LOWER";
    else return "ERROR";
}
```

`updateExistingOrder` 的处理：

```cpp
// 1) 清掉未 released 的 horizon
edgeStates.erase(remove_if(..., [](Edge e){ return !e.released; }), ...);
nodeStates.erase(remove_if(..., [](Node n){ return !n.released; }), ...);
// 2) 追加新节点/边
for (auto const &newEdge : msg->edges) edgeStates.push_back(newEdge);
for (auto const &newNode : msg->nodes) nodeStates.push_back(newNode);
// 3) 更新版本号
currentOrders.front().setOrderUpdateId(msg->orderUpdateId);
```

断点续跑的实现位置：`OrderDaemon::AgvPositionCallback` 里，节点通过后发布 `lastNodeId` / `lastNodeSequenceId`，然后 `nodeStates.pop_front()`；平台侧拿这两个值做续发锚点。

**同样要说明的坑**：`AgvPositionCallback` 在 `currentOrders.erase(currentOrders.begin())` 之后又访问 `currentOrders.front()`（空队列）——这是实现 bug，不要照抄。

### 2.4 “重复下发 / 订单更新 / 断点续跑”三件事的结论

| 问题 | VDA5050 的答案 | 开源实现怎么做 | 我们该怎么做 |
|---|---|---|---|
| 重复下发同一个 `orderId` | 同单同版是幂等重放，车端应丢弃 | inorbit `update_id_diff==0` 直接 return；tum-fml `EQUAL` 只 warn | 平台侧也按 `(order_id, attempt)` 判重：同 attempt 直接返回当前状态，不再发网络 |
| 订单更新 | 同 `orderId`、更高 `orderUpdateId`；base 必须与 `lastNodeId` 对齐；horizon 可替换 | inorbit 分 STITCH/UPDATE；tum-fml 清 horizon 后追加 | 本期不做“改单”；预留 `order_update_id`，未来只允许 `seq > last_seq` 的尾部追加 |
| 断点续跑 | 车端报 `lastNodeId/lastNodeSequenceId`；新单/更新单必须从该节点接上；`newBaseRequested` 是补发信号 | tum-fml 用 `lastNodeId/lastNodeSequenceId` 发布；RMF 用 `Backup + Resume` | 用 `task_run.last_seq`（最后成功 step）做锚；重启只重跑 `seq > last_seq`，不清已完成结果 |

---

## 3. 任务状态机：RMF / Nav2 到底怎么分层

### 3.1 RMF：派发状态 5 个，执行状态 12 个，pause 是 interruption

**派发状态**（[`rmf_task_ros2/include/rmf_task_ros2/DispatchState.hpp`](https://github.com/open-rmf/rmf_ros2/blob/main/rmf_task_ros2/include/rmf_task_ros2/DispatchState.hpp)）：

```cpp
enum class Status : uint8_t
{
  Queued = Msg::STATUS_QUEUED,                 // 还没分配
  Selected = Msg::STATUS_SELECTED,             // 选好了，但没收到中标方 ack
  Dispatched = Msg::STATUS_DISPATCHED,         // 已派发，不再由 dispatcher 管理
  FailedToAssign = Msg::STATUS_FAILED_TO_ASSIGN,
  CanceledInFlight = Msg::STATUS_CANCELED_IN_FLIGHT,
};
```

**执行状态**（[`api_server/models/rmf_api/task_state.py`](https://github.com/open-rmf/rmf-web/blob/main/packages/api-server/api_server/models/rmf_api/task_state.py)）：

```python
class Status(Enum):
    uninitialized = "uninitialized"
    blocked = "blocked"
    error = "error"
    failed = "failed"
    queued = "queued"
    standby = "standby"
    underway = "underway"
    delayed = "delayed"
    skipped = "skipped"
    canceled = "canceled"
    killed = "killed"
    completed = "completed"

class Status2(Enum):          # 这就是 DispatchState 的 5 个状态
    queued = "queued"
    selected = "selected"
    dispatched = "dispatched"
    failed_to_assign = "failed_to_assign"
    canceled_in_flight = "canceled_in_flight"
```

`TaskState` 里同时有：

```text
booking.id                 # 自然主键（幂等键）
status                     # 上表 12 个执行状态
dispatch.status            # Status2 5 个派发状态
interruptions{}            # pause/resume：带 resumed_by
cancellation / killed      # 取消/终止请求
completed / active / pending  # phase 级进度
```

**Event 的 11 个状态**（[`rmf_task/include/rmf_task/Event.hpp`](https://github.com/open-rmf/rmf_task/blob/main/rmf_task/include/rmf_task/Event.hpp)）：`Uninitialized / Blocked / Error / Failed / Standby / Underway / Delayed / Skipped / Canceled / Killed / Completed`。`Task::Active::status_overview()` 返回的正是它；`Task::Active` 还提供 `interrupt() / cancel() / kill() / skip() / rewind()`，以及带序号 `Backup` 和 `Resume` 凭据（[`Task.hpp`](https://github.com/open-rmf/rmf_task/blob/main/rmf_task/include/rmf_task/Task.hpp)）。`Backup` 的序号只保留最高的一版；`Resume` 对象调用或析构后，任务才允许继续——这就是 RMF 的“断点续跑”凭据。

> 结论：RMF 没有一个“8 态主枚举”。它把**派发**、**执行**、**中断**、**phase 进度**拆成不同结构。把 `dispatched/accepted/active/paused` 塞进一个 `status` 字段，是把四层信息压成一层。

**谁推进状态**（[`Dispatcher.cpp`](https://github.com/open-rmf/rmf_ros2/blob/main/rmf_task_ros2/src/rmf_task_ros2/Dispatcher.cpp)）：

1. `push_bid_notice()`：新任务 → `Queued`。
2. `conclude_bid()`：有中标者 → `Selected`，发 `TYPE_AWARD` 命令，并放进 `lingering_commands`；命令每秒重发，10s 过期。
3. `handle_dispatch_ack()`：收到 `DispatchAck` → `Dispatched`；**重复 ack 直接 return**（`lingering_commands` 里已经没有这个 `dispatch_id`）。
4. `cancel_task()`：只有 `Queued` / `Selected` 能取消；`Dispatched` 返回 false，交给 fleet adapter。
5. `ApiMemory`：按 `request_id` 缓存最近 50 个响应；同一个 API 请求重放，直接回缓存，不再执行。

```cpp
void handle_dispatch_ack(const DispatchAckMsg& ack)
{
  const auto command_it = lingering_commands.find(ack.dispatch_id);
  if (command_it == lingering_commands.end())
    return;  // 已经处理过这个 ack，幂等忽略

  const auto command = std::move(command_it->second);
  lingering_commands.erase(command_it);

  if (command.type == DispatchCommandMsg::TYPE_AWARD) {
    const auto state = active_dispatch_states.find(command.task_id)->second;
    if (state->status == DispatchState::Status::Selected) {
      state->status = DispatchState::Status::Dispatched;
      move_to_finished(state->task_id);
    }
  }
}
```

### 3.2 Nav2：action 状态机，没有 paused

**ROS2 action 的 7 个状态**（[`action_msgs/msg/GoalStatus.msg`](https://github.com/ros2/rcl_interfaces/blob/rolling/action_msgs/msg/GoalStatus.msg)）：

```text
STATUS_UNKNOWN   = 0
STATUS_ACCEPTED  = 1   # 已接受，等待执行
STATUS_EXECUTING = 2   # 正在执行
STATUS_CANCELING = 3   # 客户端请求取消，server 已接受
STATUS_SUCCEEDED = 4
STATUS_CANCELED  = 5
STATUS_ABORTED   = 6
```

**Nav2 action 定义**：

- [`NavigateToPose.action`](https://github.com/ros-navigation/navigation2/blob/main/nav2_msgs/action/NavigateToPose.action)：goal 是 `PoseStamped + behavior_tree`；result 是 `error_code + error_msg`；feedback 是 `current_pose/navigation_time/estimated_time_remaining/number_of_recoveries/distance_remaining/position_tracking_error/heading_tracking_error`。
- [`NavigateThroughPoses.action`](https://github.com/ros-navigation/navigation2/blob/main/nav2_msgs/action/NavigateThroughPoses.action)：goal 是 `Goals poses`；result/feedback 多了 `WaypointStatus[] waypoint_statuses` 和 `number_of_poses_remaining`。这是“一次发多个点”的官方抽象，但它仍然是**一个 action**，不是订单。

**BtActionServer 怎么处理取消/抢占**（[`bt_action_server_impl.hpp`](https://github.com/ros-navigation/navigation2/blob/main/nav2_behavior_tree/include/nav2_behavior_tree/bt_action_server_impl.hpp)）：

```cpp
auto is_canceling = [&]() {
  if (action_server_ == nullptr) return true;
  if (!action_server_->is_server_active()) return true;
  return action_server_->is_cancel_requested() || muxer_preemption_requested_;
};

auto on_loop = [&]() {
  if (action_server_->is_preempt_requested() && on_preempt_callback_)
    on_preempt_callback_(action_server_->get_pending_goal());
  on_loop_callback_();
};

BtStatus rc = bt_->run(&tree_, on_loop, is_canceling, bt_loop_duration_);
// ...
switch (rc) {
  case BtStatus::SUCCEEDED: action_server_->succeeded_current(result); break;
  case BtStatus::FAILED:    action_server_->terminate_current(result); break;
  case BtStatus::CANCELED:  action_server_->terminate_all(result); break;
}
```

没有 `pause()`；只有 `is_cancel_requested()` 和 `is_preempt_requested()`。**暂停的语义是“取消当前目标 + 平台不再发下一个点”，不是车端 action 的一个状态。**

**四个词在各家的落点**：

| 概念 | VDA5050 | Open-RMF | Nav2 | 对我们的含义 |
|---|---|---|---|---|
| `dispatched` | 没有独立枚举；看车端 `state.order_id` 是否回显、`nodeStates/edgeStates` 是否非空 | `DispatchState::Dispatched`（收到 ack 后） | `EXECUTING` 是执行，不是派发 | “已发未确认”必须平台自己记 |
| `accepted` | 没有；车端接受后直接进入执行 | `Selected` 是“已选中、未 ack”；`Dispatched` 才是 ack 后 | `ACCEPTED`（action 层） | 不要做成主状态；用 `accepted_at` 记录 |
| `active` | `nodeStates/edgeStates` 非空 + `lastNodeId` 前移 | `status=underway` + `active` phase id | `EXECUTING` | 就是我们的 `running` |
| `paused` | `paused=true` | `interruptions{}` + `resumed_by` | 没有；取消 + 重发 | 平行态，用 `paused_at` |

### 3.3 free_fleet：它是 RMF adapter，不是 VDA 实现

[`free_fleet_adapter/free_fleet_adapter/nav2_robot_adapter.py`](https://github.com/open-rmf/free_fleet/blob/main/free_fleet_adapter/free_fleet_adapter/nav2_robot_adapter.py) 的 `update()` 是典型的“adapter 轮询 action handle + 向 RMF 上报”：

```python
if nav_handle:
    is_done, succeeded = nav_handle.update(state)
    if is_done:
        self.nav_handle = None
        self.replan_counts = 0
        ...
    activity_identifier = nav_handle.get_activity()
...
self.update_handle.update(state, activity_identifier)
```

`navigate()` 里先 `_request_nav_stop()`，再新建 `NavigateToPoseActionInterface`；`stop()` 调 `nav_handle.stop()`；`RequestAborted` 会建 issue ticket 并 `replan()`（最多 5 次）。**没有 orderId/orderUpdateId**，任务身份由 RMF 的 `task_id/booking.id` 提供。

### 3.4 对照总表

| 维度 | VDA5050 | Open-RMF | Nav2 | 我们现状 | 建议 |
|---|---|---|---|---|---|
| 订单身份 | `orderId` | `task_id` / `booking.id` | 无（action goal 有 UUID） | `TaskRun.id` + `external_id` | `order_id` 稳定、可读 |
| 版本 | `orderUpdateId` | `TaskState` 每次更新整体覆盖（自然键） | 无 | 无 | `order_update_id` 单调 |
| 派发态 | 无（车端 state 回显） | `Queued/Selected/Dispatched/FailedToAssign/CanceledInFlight` | action `ACCEPTED` | 无（写库即 running） | `dispatch_state` 6 值 |
| 执行态 | `nodeStates/edgeStates/actionStates` | 12 个 `status` | `EXECUTING/SUCCEEDED/...` | 5 个 `status` | 保留 5 主态 |
| 暂停 | `paused=true` | `interruptions` + `resumed_by` | 无（取消 + 重发） | `paused_at` 标志 | 保留 `paused_at` |
| 取消中 | `cancelOrder` instantAction | `cancellation` | `CANCELING` | 无 | `cancel_requested_at` |
| 断点 | `lastNodeId/lastNodeSequenceId` | `Backup + Resume` / phase id | `NavigateThroughPoses` 的 waypoint_statuses | `from_seq` 手工传 | `last_seq` 自动锚 |
| 谁推进 | 车端周期发 state；平台发 order | dispatcher 发命令；fleet adapter ack + 上报 | action server 执行；client goal/cancel | 平台线程 3s 轮询 + ingest 推送 | 保留双通道，按 `order_id` 对账 |

**补充：NVIDIA Isaac Mission Dispatch（VDA5050 3.0）的 mission 状态**（[README](https://github.com/NVIDIA-ISAAC/isaac_mission_dispatch/blob/main/README.md)，只作行为佐证）：

```text
PENDING / RUNNING / COMPLETED / CANCELED / FAILED
```

- 取消运行中的 mission：不是立刻置 `CANCELED`，而是置 `needs_canceled=True`，**等当前 mission 跑完再取消**；删除运行中的 mission 则置 `PENDING_DELETE`，也是等跑完再删。
- `pause_order` / `startTeleop` / `stopTeleop` 是 **instantAction**，`pause_order` 明确标注 idempotent；action state 有 `Paused`，订单本身仍可 resume。
- 任务/状态持久化在 Postgres；Mission Dispatch 崩溃后从数据库重建已知状态。

这印证了两件事：**“取消中”是真实存在的中间态，不能 `running → cancelled` 一步跳；暂停是 instantAction + 平行态，不是主状态。**

---

## 4. 幂等键工程实践

### 4.1 数据库层：唯一键 + upsert 的真实用法

**RMF Web 的做法**（FastAPI + Tortoise ORM，和我们是同一类栈）：

[`models/tortoise_models/tasks.py`](https://github.com/open-rmf/rmf-web/blob/main/packages/api-server/api_server/models/tortoise_models/tasks.py)：

```python
class TaskRequest(Model):
    id_ = CharField(255, pk=True, source_field="id")
    request = JSONField()

class TaskState(Model):
    id_ = CharField(255, pk=True, source_field="id")   # 就是 booking.id
    data = JSONField()
    status = CharField(255, null=True, index=True)
    ...
```

[`repositories/tasks.py`](https://github.com/open-rmf/rmf-web/blob/main/packages/api-server/api_server/repositories/tasks.py) 的 `save_task_state()` / `save_task_request()`：

```python
async def save_task_request(self, task_state, task_request):
    await DbTaskRequest.update_or_create(
        {"request": task_request.model_dump_json()}, id_=task_state.booking.id
    )

async def save_task_state(self, task_state: TaskState):
    async with in_transaction():
        db_task_state, created = await DbTaskState.update_or_create(
            {
                "data": task_state.model_dump_json(),
                "status": task_state.status if task_state.status else None,
                ...
            },
            id_=task_state.booking.id,        # 自然键；不是自增 id
        )
        if created and task_state.booking.labels:
            await self.save_task_labels(db_task_state, ...)
```

要点：

1. **主键是业务 id（`booking.id`），不是自增 id**。同一个任务状态上报 100 次，`update_or_create` 只会有一行。
2. **先 `update_or_create` 主表，再写 labels；labels 只在 `created` 时写**，避免重复追加。
3. RMF Web 没有手写 `INSERT ... ON DUPLICATE KEY`；它用的是 ORM 的 upsert 语义（内部通常是 `get_or_create` + `update`，并发下仍可能撞主键）。**所以数据库层的主键/唯一索引不能省；要落到 SQL 方言，用下面的 SQLAlchemy 写法。**

**SQLAlchemy 2.0 方言写法**（可直接照抄）：

MySQL：

```python
from sqlalchemy.dialects.mysql import insert as mysql_insert

stmt = mysql_insert(TaskRunStep).values(
    run_id=run_id, seq=seq, point_id=point_id, point_name=point_name,
    action=action, status=status, result_json=result_json, error=error,
)
stmt = stmt.on_duplicate_key_update(
    status=stmt.inserted.status,
    point_id=stmt.inserted.point_id,
    point_name=stmt.inserted.point_name,
    action=stmt.inserted.action,
    result_json=stmt.inserted.result_json,
    error=stmt.inserted.error,
)
db.execute(stmt)
```

SQLite / PostgreSQL：

```python
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
# from sqlalchemy.dialects.postgresql import insert as pg_insert

stmt = sqlite_insert(TaskRunStep).values(
    run_id=run_id, seq=seq, point_id=point_id, point_name=point_name,
    action=action, status=status, result_json=result_json, error=error,
)
stmt = stmt.on_conflict_do_update(
    index_elements=["run_id", "seq"],
    set_={
        "status": stmt.excluded.status,
        "point_id": stmt.excluded.point_id,
        "point_name": stmt.excluded.point_name,
        "action": stmt.excluded.action,
        "result_json": stmt.excluded.result_json,
        "error": stmt.excluded.error,
    },
)
db.execute(stmt)
```

对应的原生 SQL（SQLAlchemy 在 MySQL/SQLite/Postgres 上分别编译成这两类）：

```sql
-- MySQL 8.0.19+：注意 VALUES() 已废弃，用行别名
INSERT INTO task_run_step (run_id, seq, status, result_json)
VALUES (:run_id, :seq, :status, :result_json) AS new
ON DUPLICATE KEY UPDATE
  status = new.status,
  result_json = new.result_json;

-- PostgreSQL / SQLite
INSERT INTO task_run_step (run_id, seq, status, result_json)
VALUES (:run_id, :seq, :status, :result_json)
ON CONFLICT (run_id, seq) DO UPDATE
SET status = EXCLUDED.status,
    result_json = EXCLUDED.result_json;
```

> 方言文档：[MySQL upsert](https://docs.sqlalchemy.org/en/20/dialects/mysql.html#insert-on-duplicate-key-update-upsert)、[SQLite upsert](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#insert-on-conflict-upsert)、[PostgreSQL upsert](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#insert-on-conflict-upsert)。
> 注意：MySQL/SQLite 的 unique 索引允许多个 `NULL`，所以**唯一键列可空时只能做“有值才去重”**，不能靠它防重复；真正必填的业务键（如 `order_id`）要 `NOT NULL`，或至少保证写入前一定赋值。`external_id` 这类车端可能不返回的字段，保留可空，但 ingest 侧要用 `order_id` 兜底。

### 4.2 应用层：状态机 guard 怎么写

**反例（我们现在的写法）**：

```python
existing = db.query(TaskRun).filter(TaskRun.external_id == body.external_id).first()
if existing:
    run.status = body.status          # 直接覆盖：done 之后来一条 running 会回退
    db.query(TaskRunStep).filter(...).delete()
```

两个请求并发时，`SELECT` 和 `INSERT` 之间没有互斥；`external_id` 又没有唯一约束，所以会出两行。

**正例：把“判 + 改”收敛成一条条件 UPDATE**：

```python
from sqlalchemy import update

res = db.execute(
    update(TaskRun)
    .where(
        TaskRun.id == run_id,
        TaskRun.status == "planned",
        TaskRun.dispatch_state == "pending",
    )
    .values(
        dispatch_state="sending",
        dispatch_attempt=attempt,
        order_id=order_id,
        order_update_id=0,
        dispatch_lease_until=now + timedelta(seconds=30),
        row_version=TaskRun.row_version + 1,
    )
)
if res.rowcount != 1:
    raise Conflict("当前状态不允许下发（可能已被其它请求抢占）")
db.commit()
# 先 commit 再发网络：崩溃后能靠 order_id + lease 对账
```

`rowcount` 判断是跨 MySQL/SQLite 都可用的“乐观锁”。如果一条 UPDATE 要改多张表，MySQL 用 `SELECT ... FOR UPDATE`，SQLite 用 `BEGIN IMMEDIATE`；**不要** `SELECT` 完在 Python 里判断再 `commit`。

**状态迁移 guard 表**（建议直接落成常量表/单测）：

| from `status` | from `dispatch_state` | 事件 | to | 额外 guard |
|---|---|---|---|---|
| `planned` | `pending` | 平台点“下发” | `planned`（`sending`） | 机器人空闲、preflight 通过、条件 UPDATE 抢到 |
| `planned` | `sending` | 适配器返回 2xx | `planned`（`sent`） | 记录 `order_id`、`external_id`、`dispatched_at` |
| `planned` | `sending/sent` | 超时/租约过期 | `planned`（`unknown`） | **不直接判 failed**，告警等对账 |
| `planned` | `sent` | 车端回显 `order_id` | `running` | `accepted_at=now`；`order_id` 必须匹配 |
| `running` | `acked` | 车端 `FINISHED` | `done` | `finished_at=now`；step 收尾 |
| `running` | `acked` | 车端 `FAILED` | `failed` | 记录错误码/原因 |
| `running` | `acked` | 平台 pause | `running` | `paused_at=now`；状态不变 |
| `running` | `acked` | 平台 resume | `running` | `paused_at=NULL` |
| `running` | `acked` | 平台 cancel | `running` | `cancel_requested_at=now`；等车端确认 |
| `running` | `acked` | 车端确认取消/终态 | `cancelled` | `finished_at=now` |
| `done/failed/cancelled` | 任意 | 任何迟到回报 | 不变 | 记录 event，不覆盖终态 |

**RMF 的 guard 例子**（`Dispatcher.cpp::cancel_task`）：

```cpp
if (finished_it->second->status == Status::Dispatched)
  return false;   // 已派发，取消权在 fleet adapter，不在 dispatcher

if (canceled_dispatch->status == Status::Queued) {
  canceled_dispatch->status = Status::CanceledInFlight;
  move_to_finished(task_id);
  return true;
}
if (canceled_dispatch->status == Status::Selected) {
  // 发 TYPE_REMOVE，并保留在 lingering_commands 里重试
}
// 其它状态：报错，不猜
```

**RMF 的请求级幂等**（`Dispatcher.cpp::handle_api_request`）：

```cpp
const auto check = api_memory.lookup(msg.request_id);
if (check.has_value()) {
  api_response->publish(*check);   // 同一 request_id 直接回缓存
  return;
}
```

这对应我们可选加 `Idempotency-Key`：**只用于 HTTP 重试**，不替代 `order_id`。

### 4.3 幂等键生成规则（建议直接采用）

| 键 | 生成规则 | 作用域 | 存哪 | 为什么不用 UUID |
|---|---|---|---|---|
| `order_id` | `JC-R{run.id:06d}-A{attempt:02d}`，例 `JC-R000123-A01` | 每次 attempt 一个 | `task_run.order_id`（唯一） | 可读、可对账；重放能算出同一个值 |
| `order_update_id` | 从 0 开始；只有“同一 attempt 内改单”才 +1 | 每个 `order_id` | `task_run.order_update_id` | VDA 语义；车端拒单会带回 |
| `dispatch_attempt` | 从 1 开始；旧单取消/终态后才 +1 | 每个 run | `task_run.dispatch_attempt` | 防止新旧两单同时活 |
| `external_id` | 车端返回的任务 id；没有就回填 `order_id` | 每台车/每个订单 | `task_run.external_id`（唯一） | 车端只认自己的 id；和 `order_id` 分开存 |
| `idempotency_key` | 客户端 `Idempotency-Key`；没有就 UUIDv7 | 每次 HTTP 写请求 | `task_run.idempotency_key`（唯一） | 只解决“双击/超时重试”，不是业务键 |
| `event seq` | 每个 run 从 0 递增 | 每个 run | `task_run_event.seq`（与 run_id 唯一） | 事件可重放、可审计 |
| `step key` | `(run_id, seq)` | 每个 step | 唯一索引 | 重复上报同一 seq 只更新一行 |

**不要做的事**：

- 用 `uuid4()` 当 `order_id`：每次重试都变，等于没有幂等。
- 用 `JC-{毫秒时间戳}`：并发会撞、重发会新单、日志无法对账。当前代码就是 [`task_dispatch.py:123`](../../server/app/services/task_dispatch.py#L123)。
- 用 `external_id` 一个字段承载 attempt 历史：旧单回报会覆盖新单。至少要 `order_id` + `attempt`。

---

## 5. 我们这套系统的最小改造方案

### 5.1 现状事实（代码级）

| 事实 | 位置 | 后果 |
|---|---|---|
| 主状态只有 5 个：`planned/running/done/failed/cancelled` | [`task_run.py:34`](../../server/app/models/task_run.py#L34) | 表达不了“已发未确认 / 暂停 / 取消中 / 失联” |
| `external_id` 只有普通索引，非唯一 | [`task_run.py:37`](../../server/app/models/task_run.py#L37) | 并发上报/重放可能两行 |
| `orderId = JC-{毫秒}`，每次下发都变 | [`task_dispatch.py:123`](../../server/app/services/task_dispatch.py#L123) | 重发=新车端任务，幂等靠人 |
| ingest 先查 `external_id`，再删旧 step、重插 | [`task_runs.py:196-223`](../../server/app/api/v1/task_runs.py#L196-L223) | 查写之间无互斥；done 后 running 会回退 |
| dispatch 收到 HTTP 2xx 就把 `status` 写成 `running` | [`task_dispatch.py:174`](../../server/app/services/task_dispatch.py#L174) | “发出去了”≠“车受理了” |
| 巡航启动把全部 step 重置为 `pending` | [`task_runs.py:336-341`](../../server/app/api/v1/task_runs.py#L336-L341) | 重跑清空历史结果，无法断点续跑 |
| 重启时把残留 `running` 一律标 `failed` | [`main.py:72-84`](../../server/app/main.py#L72-L84) | 状态未知被说成失败；应该进 `unknown` 对账 |
| 已有 `dispatched` 字符串残留，但模型/标签没有 | [`main.py:77`](../../server/app/main.py#L77) | 说明之前想过加态；本次改为 `dispatch_state`，不要再加主态 |

### 5.2 表改动（Alembic 0020 可加）

> **命名对齐**：现有改造规划（`docs/巡航与任务下发-改造规划.md`）用 `order_key / attempt / cancel_requested / task_event`；本文用 `order_id / dispatch_attempt / cancel_requested_at / task_run_event` 表达同一语义，落地时二选一，**不要两套列/表并存**。`order_key` 的值就是下发给车端的 `orderId`。迁移号按当时 head 顺延：当前 head 是 `0019`，如果并行改造已占用 `0020–0023`，本文的 `0020` 就改成 `0024`。
>
> `dispatch_state` 同理：4 值（`pending/sent/acked/failed`）够用；本文多出的 `sending` 可用 `pending + dispatch_lease_until` 表达，`unknown` 可用 `pending` + 对账表达。保留 6 值只是让看板能直接显示“正在发/失联”，不是强制。

#### `task_run` 新增字段

| 字段 | 类型 | 默认/可空 | 索引 | 用途 |
|---|---|---|---|---|
| `order_id`（或 `order_key`） | `String(64)` | NULL | **unique** | 平台订单号；`JC-R{id}-A{attempt}` |
| `order_update_id` | `Integer` | `0` NOT NULL | — | 同单版本号；只有改单才 +1 |
| `dispatch_state` | `String(16)` | `'pending'` NOT NULL | index | `pending/sending/sent/acked/rejected/unknown` |
| `dispatch_attempt` | `Integer` | `0` NOT NULL | — | 第几次下发；旧单终态后才 +1 |
| `dispatch_lease_until` | `DateTime` | NULL | — | 防“发到一半进程崩了”的租约 |
| `accepted_at` | `DateTime` | NULL | — | 车端回显 `order_id` 的时间 |
| `cancel_requested_at` | `DateTime` | NULL | — | 取消已发、车端未确认 |
| `last_seq` | `Integer` | `0` NOT NULL | — | 最后成功 step；断点续跑锚 |
| `idempotency_key` | `String(64)` | NULL | **unique** | HTTP 重试键（可选） |
| `row_version` | `Integer` | `0` NOT NULL | — | 乐观锁；条件 UPDATE 自增 |

#### `task_run_step` 新增索引

| 索引 | 字段 | 唯一 | 用途 |
|---|---|---|---|
| `uq_task_run_step_run_seq` | `(run_id, seq)` | 是 | 同一 run 的同一 seq 只允许一行；upsert 的冲突键 |

#### 新表 `task_run_event`（append-only）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | Integer PK | 自增 |
| `run_id` | Integer NOT NULL | 关联 `task_run.id` |
| `seq` | Integer NOT NULL | 每个 run 从 0 递增 |
| `from_status` | String(16) NULL | 旧主状态；迁移导入可为 NULL |
| `to_status` | String(16) NOT NULL | 新主状态/事件类型 |
| `source` | String(16) NOT NULL | `platform/robot/watchdog/migration` |
| `reason` | String(200) NULL | 失败原因/取消原因 |
| `payload_json` | Text NULL | 原始回包/错误码/操作者 |
| `created_at` | DateTime NOT NULL | 事件时间 |

索引：`unique(run_id, seq)`、`index(run_id, created_at)`。

> 同步新增 `TaskRunEvent` ORM 模型并注册到 `server/app/models/__init__.py`；`test_migrations.py` 只检查“模型有、库没有”的缺列/缺表，但下一次 autogenerate 会把没注册的表当成“多余表”，不要留下这个坑。

#### 其他索引

| 索引 | 字段 | 用途 |
|---|---|---|
| `uq_task_run_external_id` | `external_id` unique | 车端回报幂等；只对非 NULL 生效 |
| `uq_task_run_order_id` | `order_id` unique | 防止同一 attempt 生成两条订单 |
| `ix_task_run_dispatch_state` | `dispatch_state` | 看板/看门狗筛“待确认/失联” |
| `ix_task_run_robot_status` | `(robot_id, status)` | 替换/补充现有单列索引，服务 `task_lock`/`preflight` |

> `task_run.external_id` 现在已有普通索引 `ix_task_run_external_id`（模型 `index=True`）。新建唯一索引后，旧的可以删掉，避免同列两个索引；先确认唯一索引生效再删。

#### Alembic 片段（骨架，按现有迁移风格）

```python
# server/alembic/versions/0020_task_idempotency.py
# revision 号按实际 head 顺延（当前 head 0019；若已排到 0024 就用 0024）
revision = "0020"
down_revision = "0019"

def upgrade():
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("task_run"):
        return
    cols = {c["name"] for c in insp.get_columns("task_run")}
    for name, col in (
        ("order_id", sa.Column("order_id", sa.String(64), nullable=True)),
        ("order_update_id", sa.Column("order_update_id", sa.Integer, nullable=False, server_default="0")),
        ("dispatch_state", sa.Column("dispatch_state", sa.String(16), nullable=False, server_default="pending")),
        ("dispatch_attempt", sa.Column("dispatch_attempt", sa.Integer, nullable=False, server_default="0")),
        ("dispatch_lease_until", sa.Column("dispatch_lease_until", sa.DateTime, nullable=True)),
        ("accepted_at", sa.Column("accepted_at", sa.DateTime, nullable=True)),
        ("cancel_requested_at", sa.Column("cancel_requested_at", sa.DateTime, nullable=True)),
        ("last_seq", sa.Column("last_seq", sa.Integer, nullable=False, server_default="0")),
        ("idempotency_key", sa.Column("idempotency_key", sa.String(64), nullable=True)),
        ("row_version", sa.Column("row_version", sa.Integer, nullable=False, server_default="0")),
    ):
        if name not in cols:
            op.add_column("task_run", col)

    # 回填 + 去重后再建唯一索引；见 §5.5
    op.create_index("uq_task_run_external_id", "task_run", ["external_id"], unique=True)
    op.create_index("uq_task_run_order_id", "task_run", ["order_id"], unique=True)
    op.create_index("ix_task_run_dispatch_state", "task_run", ["dispatch_state"])
    op.create_index("ix_task_run_robot_status", "task_run", ["robot_id", "status"])
    op.create_index("uq_task_run_idem", "task_run", ["idempotency_key"], unique=True)
    op.create_index("uq_task_run_step_run_seq", "task_run_step", ["run_id", "seq"], unique=True)
    op.create_table(
        "task_run_event",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Integer, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="platform"),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("payload_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("run_id", "seq", name="uq_task_run_event_run_seq"),
    )
    op.create_index("ix_task_run_event_run_time", "task_run_event", ["run_id", "created_at"])
```

> 注意：上面是**顺序示意**。真实迁移要在建唯一索引前做 §5.5 的回填/去重，并像 `0016/0019` 一样用 `inspect` 判断列/索引是否已存在，保证可重复执行。
> SQLite 不支持 `ALTER TABLE ADD CONSTRAINT`，所以统一用 `op.create_index(..., unique=True)`，不要用 `op.create_unique_constraint`。

### 5.3 状态枚举：5 态 + 正交字段，不要 8 态

```python
# 主状态：保持 5 个，兼容现有数据/查询/前端
STATUS = ("planned", "running", "done", "failed", "cancelled")

# 派发握手：正交，不进入主状态机
DISPATCH_STATE = ("pending", "sending", "sent", "acked", "rejected", "unknown")
```

状态图：

```text
planned ──claim──▶ [dispatch_state=sending] ──2xx──▶ sent ──车端回显 order_id──▶ running ──FINISHED──▶ done
   │                    │                              │                              ├──FAILED────▶ failed
   │                    └──超时/租约过期──▶ unknown     │                              ├──pause─────▶ running(paused_at)
   └──cancel──▶ cancelled                              └──reject──▶ failed            └──cancel ack▶ cancelled
```

| 表象 | 存在哪 | 怎么判断 | 为什么不做成主状态 |
|---|---|---|---|
| 已下发、车未确认 | `dispatch_state='sent'` | `status='planned' AND dispatch_state='sent'` | 只是握手窗口，业务上还没开始 |
| 已受理 | `accepted_at` 非空 | `status='running'` | 和 `running` 同时发生，独立无决策价值 |
| 暂停 | `paused_at` 非空 | `status='running' AND paused_at IS NOT NULL` | 暂停是平行态，可 resume；做成主状态会逼出非法迁移 |
| 取消中 | `cancel_requested_at` 非空 | `status='running' AND cancel_requested_at IS NOT NULL` | 取消是异步请求，终态要等车端确认 |
| 失联 | `dispatch_state='unknown'` | 心跳/轮询连续失败 | 未知不是失败；需要人工/自动对账 |

**配套查询必须一起改**：现在 [`task_lock.py:28-30`](../../server/app/services/task_lock.py#L28-L30) 和 [`task_dispatch.py:104-108`](../../server/app/services/task_dispatch.py#L104-L108) 只查 `status='running'`。改造后，“已发未确认”（`dispatch_state='sent'`）和“失联待对账”（`dispatch_state='unknown'`）也算占用机器人，否则另一条任务会在 ack 之前挤进来：

```python
# 伪代码：active_run 的过滤条件
or_(
    TaskRun.status == "running",
    TaskRun.dispatch_state.in_(("sending", "sent", "unknown")),
)
```

`paused_at` / `cancel_requested_at` 非空时也仍然是占用状态，不要因为“暂停了”就允许新任务。

API 也要补字段：现在 [`task_runs.py:72-84`](../../server/app/api/v1/task_runs.py#L72-L84) 的 `_run_out()` 只回 `status/paused/dispatched_at`，前端看不到 `sent/unknown`。至少加 `dispatch_state`、`dispatch_attempt`、`accepted_at`、`cancel_requested_at`；否则页面还是只能靠 `status='planned'` 猜“到底发没发出去”。

> 这里的“5 态”指**主状态机只有 5 个节点**；`dispatch_state`、`paused_at`、`cancel_requested_at` 是正交字段，不参与主状态的迁移矩阵。不要把它们理解成“又加了 11 个状态”。

**为什么 5 态够**：

1. **VDA5050 没有 order 级 status**；它用 `nodeStates/edgeStates/actionStates + paused + errors` 表达。照抄“8 态主枚举”反而不像 VDA。
2. **RMF 自己就是 5 派发态 + 12 执行态 + interruption**；没有一个 8 态枚举。把 `dispatched/accepted/active/paused` 混进主状态，等于把 RMF 的三层压成一层。
3. **Nav2 的 `ACCEPTED/EXECUTING/CANCELING` 是 action 传输态**，不是业务订单状态；`paused` 根本没有。
4. **改主枚举的代价最大**：`task_lock`、`preflight`、看门狗、列表筛选、`STATUS_LABELS`、现有测试都按 `status='running'` 写。加 8 态要改一圈，收益只是“少一个字段”。
5. 真正缺的是**正交字段 + 迁移守卫**，不是更多主状态。

**如果坚持要“8 态”**：那也应该是 `planned / sending / sent / running / paused / cancelling / done|failed / cancelled` 的**展示态**，由 5 主态 + 正交字段**派生**，不要落库成第二个 `status`。落库两个状态字段会带来“两者不一致时听谁”的新问题。

### 5.4 幂等键怎么生成：run_id + attempt，不是 UUID

| 层 | 键 | 规则 | 例子 |
|---|---|---|---|
| 平台订单 | `order_id` | `JC-R{run.id:06d}-A{attempt:02d}` | `JC-R000123-A01` |
| 订单版本 | `order_update_id` | 从 0；同 attempt 内改单才 +1 | `0` |
| 下发尝试 | `dispatch_attempt` | 从 1；旧单取消/终态后才 +1 | `1` |
| 车端任务 | `external_id` | 车端返回的 id；没有就回填 `order_id` | `JC-R000123-A01` |
| HTTP 重试 | `idempotency_key` | 客户端 header；没有就 UUIDv7 | `01J...` |
| 事件 | `(run_id, seq)` | 每 run 从 0 | `(123, 0)` |
| 步骤 | `(run_id, step.seq)` | 复用 `TaskRunStep.seq` | `(123, 7)` |

> 如果现有规划已经定了 `order_key = f"{run.id}-{attempt}"`，直接用那个格式；本文的 `JC-R...` 只是加可读前缀，**不是必须**。关键是“同一 run 同一 attempt 稳定、跨 attempt 变化、可读可对账”。

**重发规则**：

1. 同一 `attempt` 重发：`order_id` 不变，`order_update_id` 不变；车端按 VDA 语义应丢弃同版。平台侧如果发现 `dispatch_state in ('sent','acked')`，直接返回当前状态，不再发网络。
2. 需要新 `attempt`：必须先 `cancel` 旧 `order_id`，确认终态（或超时后人工确认），再 `attempt += 1`，生成新 `order_id`、`order_update_id=0`。
3. `unknown` 不自动重发：先查车端 `state.order_id`；如果旧单还活着，先取消；确认不了就告警，不要“补一单试试”。
4. `external_id` 与 `order_id` 分开：车端可能只返回自己的 id；`external_id` 用于 ingest 幂等，`order_id` 用于平台对账。
5. `idempotency_key` 只做“同一 HTTP 请求不重复执行”，不缓存完整响应；重复请求返回当前 `task_run` 即可。要像 RMF `ApiMemory` 那样缓存完整响应，才需要额外的 response 表/缓存。

### 5.5 兼容现有数据的迁移策略

历史数据只有 5 个 `status`，**不改 status**；新列全部可空/带默认值，老代码/老前端不受影响。

**Step 1：加列（可空/默认）**

- 按 §5.2 加 `task_run` 新列；`task_run_step` 先不加唯一索引。
- 旧行 `dispatch_state` 默认 `pending`，`order_id` 为 NULL。

**Step 2：回填 `order_id`（先把空串归一为 NULL）**

```sql
UPDATE task_run SET external_id = NULL WHERE external_id = '';

-- 伪 SQL：external_id 非空就用它；否则用 id 生成
UPDATE task_run
SET order_id = COALESCE(
    (SELECT external_id FROM task_run t2 WHERE t2.id = task_run.id AND t2.external_id IS NOT NULL),
    'JC-R' || printf('%06d', id) || '-A01'
)
WHERE order_id IS NULL;
```

MySQL 用 `LPAD(id, 6, '0')` 替代 `printf`；SQLite 用 `printf`。更稳妥的是在 Alembic 里用 Python 逐行生成，避免方言差异。
**新代码禁止再写 `external_id=''`**：`task_dispatch.py:175` 现在是 `str(res.get("id") or run.external_id or "")`，要改成“没有 id 就保持 NULL”，否则唯一索引只能容纳一个空串。

**Step 3：回填 `dispatch_state` / `accepted_at`**

| 历史 `status` | `dispatch_state` | `accepted_at` | 说明 |
|---|---|---|---|
| `planned` | `pending` | NULL | 从未下发 |
| `running` | `sent` | `started_at` 或 `dispatched_at` | 不知道是否 ack；按“已发出”对待 |
| `done` | `acked` | `started_at` 或 `dispatched_at` | 已终态 |
| `failed` | `acked` | `started_at` 或 `dispatched_at` | 已终态 |
| `cancelled` 且 `dispatched_at IS NULL` | `pending` | NULL | 计划阶段取消 |
| `cancelled` 且 `dispatched_at` 非空 | `unknown` | `dispatched_at` | 下发后取消，是否真停未知 |

**Step 4：回填 `last_seq`**

```sql
UPDATE task_run
SET last_seq = COALESCE((
    SELECT MAX(seq) FROM task_run_step s
    WHERE s.run_id = task_run.id AND s.status = 'ok'
), 0);
```

**Step 5：去重 `external_id`（建唯一索引前）**

保留每个 `external_id` 的最新一行（`MAX(id)`），旧行把 `external_id` 置 NULL 并在 `note` 里留痕，避免删历史：

```sql
UPDATE task_run
SET note = COALESCE(note, '') || ' [legacy duplicate external_id]',
    external_id = NULL
WHERE external_id IS NOT NULL
  AND id NOT IN (
      SELECT keep_id FROM (
          SELECT MAX(id) AS keep_id FROM task_run
          WHERE external_id IS NOT NULL
          GROUP BY external_id
      ) x
  );
```

MySQL 不允许在 UPDATE 子查询里直接查同一张表，需要派生表包一层（上面的 `x` 就是为此）。

**Step 6：去重 `(run_id, seq)`（建唯一索引前）**

1. 先把 `seq <= 0` 的 step 按 `id` 顺序重编号为 `1..N`（`StepIn.seq` 默认 0，机器人可能漏传，多个 0 会撞唯一索引）。
2. 保留每个 `(run_id, seq)` 的最新一行；旧行 `seq = seq + 100000` 保留证据（或者移到归档表）。这一步必须做，否则唯一索引建不上。
3. 新 ingest 校验 `seq >= 1`；缺省时按数组下标补，不要留 0。

**Step 7：建唯一索引 + 事件表**

- `uq_task_run_external_id`、`uq_task_run_order_id`、`uq_task_run_idem`、`uq_task_run_step_run_seq`。
- 建 `task_run_event`；给每条历史 run 插一条 `seq=0, from_status=NULL, to_status=status, source='migration', reason='历史数据导入'` 的事件，保证时间轴从第一天开始。

**Step 8：启动逻辑调整（不是迁移，但必须同批上线）**

现在 [`main.py:72-84`](../../server/app/main.py#L72-L84) 把重启前残留的 `running` 一律标 `failed`。改造后：

- `running` → `dispatch_state='unknown'`，`status` 保持 `running`；
- 写一条 `task_run_event(source='watchdog', reason='服务重启，状态未知')`；
- 看板显示“状态未知，待对账”，不显示“失败”；
- 对账确认后再落 `done/failed/cancelled` 或恢复 `running`。

**Step 9：可重复执行**

- 所有 `add_column` / `create_index` 前用 `sa.inspect()` 判断是否已存在（照 `0016/0019` 的写法）；
- 回填 SQL 用 `WHERE order_id IS NULL` / `WHERE dispatch_state='pending'` 这类幂等条件；
- 事件表回填用 `NOT EXISTS (SELECT 1 FROM task_run_event WHERE run_id=... AND seq=0)`；
- 迁移失败时不要 `DROP` 已加的列；先修复再重跑。

**Step 10：回滚**

- 先停写、备份 `task_run` / `task_run_step`；
- `downgrade()` 只删新索引/新列/事件表；不恢复历史 status（本来就没改）；
- 事件表删除会丢审计，回滚前导出。

### 5.6 “照抄哪个仓库的哪段逻辑”清单

| 要抄的行为 | 仓库 / 文件 / 函数 | 抄什么 | 不要抄什么 |
|---|---|---|---|
| 同单同版丢弃、低版拒绝、base 不匹配拒绝 | [`inorbit vda5050_controller.py::process_order`](https://github.com/inorbit-ai/ros_amr_interop/blob/galactic-devel/vda5050_connector/vda5050_connector/vda5050_controller.py#L837-L912) | 判定顺序和错误类型（`ORDER_UPDATE_ERROR`） | `order_msg_is_valid()` 的 `TODO return True`；`nodes_states/sequenceId` 拼写 bug |
| STITCH/UPDATE 的 horizon 处理 | 同文件 `_accept_order` `#L996-L1080` | 清未 released 的 horizon、保留 base、追加新节点 | 逐字复制字段名；当前实现有拼写错误 |
| 订单更新/新单的 base 比较 | [`tum-fml order_daemon.cpp::OrderCallback`](https://github.com/tum-fml/vda5050_connector/blob/current_ros_noetic/src/order_daemon.cpp) | `LOWER/EQUAL/HIGHER` 三档 + `compareBase` 的顺序 | `AgvPositionCallback` 里 erase 后 `front()` 的空队列 bug |
| 派发 5 态 + ack 去重 + 取消 guard | [`rmf_ros2 DispatchState.hpp`](https://github.com/open-rmf/rmf_ros2/blob/main/rmf_task_ros2/include/rmf_task_ros2/DispatchState.hpp)、[`Dispatcher.cpp`](https://github.com/open-rmf/rmf_ros2/blob/main/rmf_task_ros2/src/rmf_task_ros2/Dispatcher.cpp) | `Queued→Selected→Dispatched`；重复 ack 直接 return；`Dispatched` 不让 dispatcher 取消 | 5 个派发态不要塞进我们的主状态 |
| 执行状态与派发状态分离 | [`task_state.py`](https://github.com/open-rmf/rmf-web/blob/main/packages/api-server/api_server/models/rmf_api/task_state.py) 的 `Status/Status2`；[`Event.hpp`](https://github.com/open-rmf/rmf_task/blob/main/rmf_task/include/rmf_task/Event.hpp) | `status` 与 `dispatch.status` 两个字段；`interruptions/resumed_by` | 12 个执行状态不要全搬；我们只需要 5 个 |
| 自然键 upsert | [`rmf-web repositories/tasks.py::save_task_state`](https://github.com/open-rmf/rmf-web/blob/main/packages/api-server/api_server/repositories/tasks.py) | `update_or_create(..., id_=booking.id)`；先主表后 labels | 不要用自增 id 当幂等键 |
| Nav2 的取消/抢占/终态 | [`bt_action_server_impl.hpp::executeCallback`](https://github.com/ros-navigation/navigation2/blob/main/nav2_behavior_tree/include/nav2_behavior_tree/bt_action_server_impl.hpp) | `is_cancel_requested || muxer_preemption_requested`；`SUCCEEDED/FAILED/CANCELED` 三分支 | 不要给 action 加 `paused` 状态 |
| 断点续跑 | [`OrderState.msg`](https://github.com/inorbit-ai/ros_amr_interop/blob/galactic-devel/vda5050_msgs/msg/OrderState.msg) 的 `last_node_id/last_node_sequence_id`；[`Task.hpp`](https://github.com/open-rmf/rmf_task/blob/main/rmf_task/include/rmf_task/Task.hpp) 的 `Backup/Resume` | `last_seq` 锚点 + 只重跑未完成 step | 不要序列化整个 `Task` 备份；我们只需要一个整数 |
| 取消中不硬跳 | [NVIDIA Mission Dispatch README](https://github.com/NVIDIA-ISAAC/isaac_mission_dispatch/blob/main/README.md) 的 `needs_canceled` / `PENDING_DELETE` | 先写 `cancel_requested_at`，等车端终态；超时进 `unknown` 对账 | 不要无限等；不要直接 `running → cancelled` |

---

## 6. 我们采用方案（含放弃项及理由）
1. **主状态保留 5 态** `planned/running/done/failed/cancelled`，不扩 8 态；派发握手放 `dispatch_state`，暂停放 `paused_at`，取消中放 `cancel_requested_at`。
2. **订单键** `order_id=JC-R{run_id:06d}-A{attempt:02d}`，`order_update_id` 单调，`attempt` 仅在旧单取消/终态后 +1；**不用 UUID 当业务键**。
3. **入库键** `external_id` 唯一 + `(run_id,seq)` 唯一 + `task_run_event(run_id,seq)` 唯一；HTTP 重试才用 `Idempotency-Key`。
4. **防并发** 用条件 `UPDATE ... WHERE status=:from AND dispatch_state=:from` 抢锁，`rowcount=0` 返回 409；禁止 `SELECT` 后裸写。
5. **重复上报** 主表按 `external_id` 定位 + 状态只允许单调迁移，step 按 `(run_id,seq)` upsert；旧序号/终态后的回报只记事件，不回退。
6. **断点续跑** 用 `task_run.last_seq`（最后成功 step）替代客户端传 `from_seq`；重启只重置 `seq>last_seq`，保留已完成结果。
7. **迁移** Alembic 0020（或按 head 顺延）：先加可空列/默认值 → 回填 → 去重 → 建唯一索引 → 建事件表；历史 5 态不改，`main.py` 的残留 `running` 改为 `unknown`。
8. **照抄** inorbit `process_order` 的判定顺序、RMF `DispatchState` 的 5 态与 ack 去重、RMF Web `save_task_state` 的自然键 upsert、Nav2 `BtActionServer` 的 cancel/preempt。
9. **放弃 8 态主枚举**：RMF 都把 dispatch 与 execution 分开，VDA 根本没有 order status；8 态会破坏现有 `status='running'` 查询、`task_lock` 和测试。
10. **放弃整单 base/horizon**：X30/JCROB 一次只接一个目标点，`released/newBaseRequested` 用不上；等真机支持整单再引入。
11. **放弃 Redis/分布式锁与独立 outbox 表**：单机 1–2 车，DB 条件 UPDATE + 唯一索引 + 事件表足够；多实例/多消费者再上。
12. **放弃自动重试**：`dispatch_state=unknown` 只告警/对账，必须人工确认旧单终态后再新 attempt，避免新旧两单同时活。
13. **验收** 同单重放 100 次只有 1 行/1 事件；双击下发只 1 次成功；拔网 60s 进 `unknown` 不判 `failed`；重启从 `last_seq` 续跑且不清旧结果。

## 7. 参考链接（核实于 2026-10-27）

**VDA5050**
- 规范：[VDA5050/VDA5050](https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md)
- inorbit connector：[`vda5050_controller.py`](https://github.com/inorbit-ai/ros_amr_interop/blob/galactic-devel/vda5050_connector/vda5050_connector/vda5050_controller.py#L837-L912)
- inorbit 消息：[`Order.msg`](https://github.com/inorbit-ai/ros_amr_interop/blob/galactic-devel/vda5050_msgs/msg/Order.msg)、[`Node.msg`](https://github.com/inorbit-ai/ros_amr_interop/blob/galactic-devel/vda5050_msgs/msg/Node.msg)、[`OrderState.msg`](https://github.com/inorbit-ai/ros_amr_interop/blob/galactic-devel/vda5050_msgs/msg/OrderState.msg)
- ipa320 的 ROS1 实现（可读替代，非同一仓库）：[`tum-fml/vda5050_connector@current_ros_noetic`](https://github.com/tum-fml/vda5050_connector/tree/current_ros_noetic)
- ROS Index（确认 inorbit 是 ROS 发布的 `vda5050_connector`）：<https://index.ros.org/p/vda5050_connector/>

**Open-RMF**
- 派发状态：[`DispatchState.hpp`](https://github.com/open-rmf/rmf_ros2/blob/main/rmf_task_ros2/include/rmf_task_ros2/DispatchState.hpp)
- 派发流程：[`Dispatcher.cpp`](https://github.com/open-rmf/rmf_ros2/blob/main/rmf_task_ros2/src/rmf_task_ros2/Dispatcher.cpp)
- 执行状态：[`task_state.py`](https://github.com/open-rmf/rmf-web/blob/main/packages/api-server/api_server/models/rmf_api/task_state.py)
- 事件/中断：[`Event.hpp`](https://github.com/open-rmf/rmf_task/blob/main/rmf_task/include/rmf_task/Event.hpp)、[`Task.hpp`](https://github.com/open-rmf/rmf_task/blob/main/rmf_task/include/rmf_task/Task.hpp)
- 自然键 upsert：[`tortoise_models/tasks.py`](https://github.com/open-rmf/rmf-web/blob/main/packages/api-server/api_server/models/tortoise_models/tasks.py)、[`repositories/tasks.py`](https://github.com/open-rmf/rmf-web/blob/main/packages/api-server/api_server/repositories/tasks.py)
- Demo 的 bidding 说明：[`rmf_demos/README.md`](https://github.com/open-rmf/rmf_demos/blob/main/README.md)（只作流程佐证，不含状态机代码）

**Nav2**
- action 定义：[`NavigateToPose.action`](https://github.com/ros-navigation/navigation2/blob/main/nav2_msgs/action/NavigateToPose.action)、[`NavigateThroughPoses.action`](https://github.com/ros-navigation/navigation2/blob/main/nav2_msgs/action/NavigateThroughPoses.action)
- action 状态：[`GoalStatus.msg`](https://github.com/ros2/rcl_interfaces/blob/rolling/action_msgs/msg/GoalStatus.msg)
- 取消/抢占：[`bt_action_server_impl.hpp`](https://github.com/ros-navigation/navigation2/blob/main/nav2_behavior_tree/include/nav2_behavior_tree/bt_action_server_impl.hpp)

**其他**
- NVIDIA Isaac Mission Dispatch（VDA5050 3.0）：[README](https://github.com/NVIDIA-ISAAC/isaac_mission_dispatch/blob/main/README.md)
- free_fleet（非 VDA）：[`Nav2RobotAdapter`](https://github.com/open-rmf/free_fleet/blob/main/free_fleet_adapter/free_fleet_adapter/nav2_robot_adapter.py)
- SQLAlchemy upsert 文档：[MySQL](https://docs.sqlalchemy.org/en/20/dialects/mysql.html#insert-on-duplicate-key-update-upsert)、[SQLite](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#insert-on-conflict-upsert)、[PostgreSQL](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#insert-on-conflict-upsert)
