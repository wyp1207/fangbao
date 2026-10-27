# 多机器人资源互斥 / 定位初始化 —— 开源实现细节与最小落地方案

> 目标：把「多机抢同一份物理资源」和「机器狗怎么知道自己在哪」这两件事，落到**能直接写代码**的程度。
> 方法：**读仓库源码**，不靠博客。所有代码事实都给了仓库 + 分支 + 文件 + 行号；规范事实给原文行号；经验阈值单独标注，不混进"事实"。
> 快照时间：2026-10-27。GitHub 直连在本机不稳定，源码通过 jsDelivr 的 GitHub 镜像按 `@main` / `@humble` 拉取到本地 `.research/mirror/` 后逐行阅读，行号与当日分支一致；上游后续提交可能让行号漂移。
> 适用代码：`server/app/services/task_lock.py`、`server/app/adapters/deeprobotics/adapter.py`、`server/app/models/map_library.py`、`server/app/services/cruise.py`。

---

## 0. 一页结论（先看这 8 条）

1. **RMF 里没有"资源表"**。共享资源被表达成两样东西：①车把**未来轨迹**登记进中央日程库（`schedule::Participant::set(plan, itinerary)`）；②路网 lane 上挂**事件**（`Door` / `LiftSession` / `Dock` / `Wait`），每个事件只带"名字/楼层 + duration"。资源=路径上的一个显式占有点，不是一张锁表。([Graph.hpp L357-L504](https://github.com/open-rmf/rmf_traffic/blob/main/rmf_traffic/include/rmf_traffic/agv/Graph.hpp#L357-L504))
2. **RMF 防死锁靠"预约 + 不许进环"，不靠超时、不靠抢占**。blockade 的 `Moderator` 给每台车分配一段"允许自由行走的 checkpoint 区间"，并在依赖图里**找环**；检出环就把这条约束加进去，让 `has_gridlock()` 为真、拒绝再放行。([Constraint.cpp L589-L670](https://github.com/open-rmf/rmf_traffic/blob/main/rmf_traffic/src/rmf_traffic/blockade/Constraint.cpp#L589-L670)、[Moderator.hpp L137-L138](https://github.com/open-rmf/rmf_traffic/blob/main/rmf_traffic/include/rmf_traffic/blockade/Moderator.hpp#L137-L138))
3. **它自己承认"取消会永久死锁"**：`Participant::cancel()` 的注释原文——"if a path is canceled while the robot is in space that it needs to share with other robots, a permanent deadlock could result."（[Participant.hpp L64-L67](https://github.com/open-rmf/rmf_traffic/blob/main/rmf_traffic/include/rmf_traffic/blockade/Participant.hpp#L64-L67)）所以"平台超时强拆锁"这条我们必须自己补，RMF 不提供。
4. **rmf_task 的三档语义是 `interrupt` / `cancel` / `kill`，没有 `pause`**。`interrupt()` 返回一个 `Resume` 凭据（人工接管/消防介入后凭它恢复）；`cancel()` 是优雅的、允许继续跑收尾 phase；`kill()` 立刻回安全态且**压过 cancel**。源码里还留着 "TODO: Should we have a pause() interface?"（[Task.hpp L283-L326](https://github.com/open-rmf/rmf_task/blob/main/rmf_task/include/rmf_task/Task.hpp#L283-L326)、[L296-L299](https://github.com/open-rmf/rmf_task/blob/main/rmf_task/include/rmf_task/Task.hpp#L296-L299)）
5. **`/initialpose` 的 covariance，AMCL 只读 5 个数**：`[0]`(x)、`[1]`/`[6]`(xy 相关)、`[7]`(y)、`[35]`(yaw)。填 `diag(0.25, 0.25, 0, 0, 0, 0.0685)` 就是"±0.5 m / ±15°"，与 AMCL 自己在"完全不知道位姿"时的兜底先验一致（[amcl_node.cpp L496-L506](https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/src/amcl_node.cpp#L496-L506)、[L1483-L1486](https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/src/amcl_node.cpp#L1483-L1486)）。
6. **两个会让人翻车的细节**：①`/initialpose` 的 `header.stamp` 若早于"现在"，AMCL 会把这段时间的 odom 增量**乘到**你给的位姿上（`pose_new = pose_old * tx_odom`），时间戳旧 2 秒 = 位姿凭空往前跳 2 秒的里程（[L447-L479](https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/src/amcl_node.cpp#L447-L479)）；②`/map_server/load_map` 换图后，AMCL **只释放地图内存、不清粒子滤波、不清 `initial_pose_is_known_`**，会拿旧图上的位姿继续跑（[L1300-L1353](https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/src/amcl_node.cpp#L1300-L1353)）。
7. **`slam_toolbox` 没有 `/slam_toolbox/set_pose` 这个服务**（全仓 grep 不到 `set_pose`；README 里写的是"复用 AMCL 的 `/initialpose`"）。它的重定位入口是：localization 模式下订阅 `/initialpose`（**covariance 被直接丢弃**），或用 `/slam_toolbox/deserialize_map` 的 `match_type=LOCALIZE_AT_POSE`；`save_map`/`serialize_map` 在 localization 模式被主动禁用。（[README L107](https://github.com/SteveMacenski/slam_toolbox/blob/humble/README.md#L107)、[localization.cpp L32-L46](https://github.com/SteveMacenski/slam_toolbox/blob/humble/src/slam_toolbox_localization.cpp#L32-L46)、[L102-L113](https://github.com/SteveMacenski/slam_toolbox/blob/humble/src/slam_toolbox_localization.cpp#L102-L113)、[L209-L239](https://github.com/SteveMacenski/slam_toolbox/blob/humble/src/slam_toolbox_localization.cpp#L209-L239)）
8. **判断"该不该重定位"要用 `localized`/`location_status` 这种硬布尔，不要用 quality 分数**。VDA5050 规范原文对 `localizationScore` 的定性是 "Only for logging and visualization purposes"，而 `localized=false` 是强制项：必须报 `LOCALIZATION_ERROR`(FATAL)、且"shall not resume automatic driving"。（[VDA5050_EN.md L1815-L1817](https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md#L1815-L1817)、[L1174](https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md#L1174)）

---

## 1. 一、资源互斥 / 交通管制

### 1.1 RMF 怎么表达"共享资源"

| 层 | 代码里的东西 | 关键字段/签名 | 含义 | 对我们的映射 |
|---|---|---|---|---|
| 日程库 | `schedule::Participant::set(PlanId plan, std::vector<Route> itinerary)` | `plan` 单调、`itinerary` 是未来轨迹；`cumulative_delay(plan)` 报累计延误 | 车把"我打算怎么走"登记进中央库，冲突检测基于**时空重叠** | 我们没轨迹、没路网，这一层跳过 |
| 路网事件 | `Graph::Lane::Door` / `DoorOpen` / `DoorClose` | `name` + `duration` | 门是一个"必须等 duration 才能通过"的点 | 门禁/闸机可建成 `door:{id}` 资源 |
| 路网事件 | `Graph::Lane::LiftSession` / `LiftSessionBegin` / `LiftMove` / `LiftDoorOpen` / `LiftSessionEnd` | **`lift_name` + `floor_name`** + `duration` | 电梯不是一个锁，是"某层某门的一次会话" | 电梯 key 必须是 `lift:{id}:{floor}`，不能只用 `lift:{id}` |
| 路网事件 | `Graph::Lane::Dock` | `dock_name` + `duration` | 充电桩/停靠位是 lane 上的一个 dock 事件 | 充电桩 = `charger:{id}` + `dock_point` |
| 路网事件 | `Graph::Lane::Wait` | `duration` | 纯等待点（会让点/待避点） | 窄道会让的 hold point |
| 能力分级 | RMF fleet adapter 四档（Full / Traffic Light / Read Only / No Interface） | — | 只读车队不能参与互斥（[RMF Core 文档](https://osrf.github.io/ros2multirobotbook/rmf-core.html)） | X30 无 pause、JCROB 无 pause → 只能当"被锁的一方"，不能当"协商方" |

代码位置：[Graph.hpp L350-L504](https://github.com/open-rmf/rmf_traffic/blob/main/rmf_traffic/include/rmf_traffic/agv/Graph.hpp#L350-L504)（`Lane::Door` L357、`LiftSession` L392、`Dock` L458、`Wait` L490）、[Participant.hpp L40-L56](https://github.com/open-rmf/rmf_traffic/blob/main/rmf_traffic/include/rmf_traffic/schedule/Participant.hpp#L40-L56)。

> **一句话**：RMF 的"资源"= 轨迹上的事件 + 时间窗。它不维护 `resource` 表，因为它的前提是"所有车都能被精确排程"。我们两台车、无路网、车端不能改道，这个前提不成立。

### 1.2 RMF 怎么防死锁（读代码后的准确结论）

| 问题 | 代码事实 | 结论 |
|---|---|---|
| 会不会排序抢锁？ | RMF 没有"抢锁"动作。`Moderator::set()` 收下整条 path 的 reservation（`Checkpoint{position, map_name, can_hold}` + `radius`），由 Moderator 计算"允许走的区间"`Assignments::ranges()` | 不是锁排序，是**集中分配通行区间** |
| 会不会超时放弃？ | `blockade` 里没有任何 deadline/超时参数；`Writer` 接口只有 `set/ready/release/reached/cancel` | **没有超时**。卡住就卡住，靠上层/人 |
| 怎么发现死锁？ | `compute_gridlock_constraint()` 在 blocker 依赖图里 DFS，`loop_found` 时把环上约束合成 `OrConstraint`；`Moderator::has_gridlock()` = `!gridlock->evaluate(ranges)` | **环检测**，只报告，不自动解 |
| 怎么避免进环？ | 环约束参与"能不能 ready"的判定；不满足就不给新区间 | **准入控制**（不让它进环），不是事后抢占 |
| 会不会抢占？ | `rmf_task` 只有 `cancel`/`kill`；`BinaryPriorityScheme` 只有高/低两档，优先级只进规划代价（`priority_penalty` 默认 10000），**不改运行中任务** | **不抢占运输任务**；只抢占"无限期充电"（见 1.8） |

代码：[Writer.hpp L37-L48](https://github.com/open-rmf/rmf_traffic/blob/main/rmf_traffic/include/rmf_traffic/blockade/Writer.hpp#L37-L48)、[Moderator.hpp L109-L138](https://github.com/open-rmf/rmf_traffic/blob/main/rmf_traffic/include/rmf_traffic/blockade/Moderator.hpp#L109-L138)、[Constraint.cpp L573-L671](https://github.com/open-rmf/rmf_traffic/blob/main/rmf_traffic/src/rmf_traffic/blockade/Constraint.cpp#L573-L671)、[BinaryPriorityScheme.hpp L29-L39](https://github.com/open-rmf/rmf_task/blob/main/rmf_task/include/rmf_task/BinaryPriorityScheme.hpp#L29-L39)、[BinaryPriorityCostCalculator.hpp L31-L38](https://github.com/open-rmf/rmf_task/blob/main/rmf_task/src/rmf_task/BinaryPriorityCostCalculator.hpp#L31-L38)。

环检测的核心 12 行（`Constraint.cpp` L641-L664，删了注释）：

```cpp
test_state.clear();
test_state[participant] = ReservedRange{index, index};
for (const auto& dep : it->second) {
  std::optional<bool> opt_eval = dep.constraint->partial_evaluate(test_state);
  if (!opt_eval.has_value() || opt_eval.value()) continue;   // 没被挡，不构成依赖边
  Cache new_visited = top->visited;
  const bool loop_found = !new_visited[dep.participant].insert(dep.index).second;
  auto next = std::make_shared<GridlockNode>(GridlockNode{dep, top, std::move(new_visited)});
  if (loop_found) gridlock_constraints.push_back(compute_gridlock_constraint(next));
  else            queue.push_back(next);
}
```

**对我们的直接启示**：这套东西的正确用法不是"照抄"，而是抄它的三个判定——① `can_hold`（这个点能不能停着等）②依赖环检测（谁在等谁）③"进环前拒绝"。我们的 `resource_wait` + 持有者表，正好够建一张小的 wait-for 图，用来做**死锁兜底**（见第 3.3 节）。

### 1.3 协商（Negotiation）：知道它是什么，然后决定不用

| API | 语义（原文） | 对我们的含义 |
|---|---|---|
| `Table` | "a view of what the other negotiation participants have proposed"，按 `to_accommodate` 形成层级 | 每张表=一个"谁迁就谁"的方案 |
| `submit(plan_id, itinerary, version)` | 提交并带版本；版本不大于上次则忽略 | 天然幂等，靠 version |
| `reject(version, rejected_by, alternatives)` | 拒绝时**必须给 alternatives（自己能让的 rollouts）**，让提议方改 | 拒绝不是"不行"，是"这样不行，那样行" |
| `forfeit(version)` | 找不到可行方案就退出这张表 | 有"认输"语义 |
| `ready()` / `complete()` | ready=存在全体同意的方案；complete=所有方案已收齐可评估 | 两个终止判据，**没有 deadline** |
| `Evaluator::choose` / `QuickestFinishEvaluator` | 由第三方在多个 proposal 里选"净延误最小"的 | 裁决者模式 |

代码：[Negotiation.hpp L81-L90](https://github.com/open-rmf/rmf_traffic/blob/main/rmf_traffic/include/rmf_traffic/schedule/Negotiation.hpp#L81-L90)、[L287-L343](https://github.com/open-rmf/rmf_traffic/blob/main/rmf_traffic/include/rmf_traffic/schedule/Negotiation.hpp#L287-L343)、[L495-L536](https://github.com/open-rmf/rmf_traffic/blob/main/rmf_traffic/include/rmf_traffic/schedule/Negotiation.hpp#L495-L536)。

**为什么我们学不了**：`reject(alternatives)` 要求车端能"换一条路/让到某个点"，X30 只有"发目标/取消/重置定位"，JCROB 只有整单 `sub_tasks`，**都没有 pause 和改道**。协商在我们这里会退化成"两台车互相拒绝到超时"。

### 1.4 rmf_task 的三档语义（这张表建议直接映射进 `task_run_event`）

| 档 | API | 语义 | 可恢复？ | 凭据 | 我们的对应 |
|---|---|---|---|---|---|
| 挂起/接管 | `interrupt(cb) -> Resume` | 允许别的指令插进来（人工接管、消防），任务暂停但不结束 | ✅ 用 `Resume` 恢复；`Resume` 析构也等于"可以恢复" | `Resume` 对象（RAII） | 现在的 `takeover()` 直接 `cancelled`，**丢掉了可恢复性**；应改成 `paused` + `resume_token` |
| 取消 | `cancel()` | 优雅取消：**允许继续跑收尾 phase**（回充电桩/卸货），跑到 finished 才算取消完成 | 半可恢复（取决于实现） | 无 | 我们 `status=cancelled` + 立刻停车，语义比 RMF 更硬 |
| 杀 | `kill()` | 尽快回安全 idle，**即使还带着货**；`kill` 压过 `cancel`，之后 `cancel` 无效 | ❌ | 无 | 急停/消防场景 |
| 检查点 | `backup()` | 带序号的字符串快照，**只保留最大序号** | ✅ | `Backup{seq, state}` | 我们的 `from_seq` 是雏形，但没有 state 快照 |
| 跳步/回退 | `skip(phase_id)` / `rewind(phase_id)` | 运维手工解卡 | — | — | 我们 `steps/{seq}/retry` 只覆盖"重试"，没有"跳过" |

代码：[Task.hpp L237-L247](https://github.com/open-rmf/rmf_task/blob/main/rmf_task/include/rmf_task/Task.hpp#L237-L247)、[L275-L347](https://github.com/open-rmf/rmf_task/blob/main/rmf_task/include/rmf_task/Task.hpp#L275-L347)。

### 1.5 free_fleet：多机接入同一平台的最小约束

`free_fleet` 是 RMF 的 Python 车队适配器（Zenoh 跨机）。它本身**不做资源互斥**，只做"把每台车的状态喂给 RMF、把 RMF 的路径指令翻成 Nav2 action"。所以它能告诉我们的，是"多机接同一平台，最少要约定什么"。

它的配置（`free_fleet_examples/config/fleet/nav2_tb3_simulation_fleet_config.yaml`）实际约束了 6 件事（下面为省篇幅合并了部分多行写法）：

```yaml
rmf_fleet:
  name: "turtlebot3"
  limits: {linear: [0.5, 0.75], angular: [0.6, 2.0]}   # 速度/加速度上限
  profile: {footprint: 0.3, vicinity: 0.5}             # 半径（m）
  recharge_threshold: 0.10                             # 低于 10% 不再接活
  recharge_soc: 1.0                                    # 充到 100%
  robots:
    nav2_tb3:
      charger: "tb3_charger"                           # 每台车指定充电桩
      initial_map: "L1"
      maps: {L1: {map_url: ".../tb3_sandbox.yaml"}}     # level -> 地图文件
      # initial_pose: [-1.6, -0.5, 0]
  robot_state_update_frequency: 10.0                   # Hz
reference_coordinates:                                 # 机器人坐标系 -> RMF 坐标系
  L1: {rmf: [[8.95,-6.60], ...], robot: [[-1.04,2.54], ...]}
```

对应代码事实：

| 约束 | 代码/配置 | 为什么必须有 |
|---|---|---|
| **位姿必须带 map 名** | `rmf_easy.RobotState(robot.get_map_name(), pose, battery)`（[fleet_adapter.py L246-L258](https://github.com/open-rmf/free_fleet/blob/main/free_fleet_adapter/free_fleet_adapter/fleet_adapter.py#L246-L258)） | 没有 map 名的 (x,y) 是无效数据 |
| **位姿从 TF 取，取不到就不更新** | `get_pose()` 拿 `map→base` 变换，异常返回 `None`（[nav2_robot_adapter.py L315-L341](https://github.com/open-rmf/free_fleet/blob/main/free_fleet_adapter/free_fleet_adapter/nav2_robot_adapter.py#L315-L341)） | TF 断了 = 这台车"消失"，而不是拿旧位姿硬撑 |
| **10 Hz 状态更新** | `robot_state_update_frequency`，`publish_fleet_state` 必须同频（配置文件 L27、L50） | 调度侧的时间窗按这个频率算 |
| **跨坐标系要对齐** | `compute_transforms()` 用 4 组对应点做相似变换并打印 MSE（[fleet_adapter.py L43-L58](https://github.com/open-rmf/free_fleet/blob/main/free_fleet_adapter/free_fleet_adapter/fleet_adapter.py#L43-L58)） | 机器人地图原点和平台地图原点不一致时，必须有显式标定 |
| **每台车指定充电桩** | `charger: "tb3_charger"` | RMF 用"专属充电桩"绕开了排队问题（见 1.8） |
| **换图** | 配置里有 `maps`，但代码是 TODO：`// TODO(ac): change map using map_server load_map, and set initial position again with /initialpose`（[nav2_robot_adapter.py L522-L524](https://github.com/open-rmf/free_fleet/blob/main/free_fleet_adapter/free_fleet_adapter/nav2_robot_adapter.py#L522-L524)） | 连成熟开源都**没实现**"换图 + 重新初始化"的闭环，这块必须我们自己写 |

`initial_pose` 在配置里是注释掉的（L48），说明 free_fleet 也把"初始定位"当人工步骤，而不是自动流程。

### 1.6 ros_amr_interop：多机状态契约（不是调度器）

`inorbit-ai/ros_amr_interop` 实现 MassRobotics AMR Interop 的 `statusReport`。它不做互斥，但它定义的字段是"多机同平台"最低限度的互操作契约：

| 字段 | 定义 | 对我们的用处 |
|---|---|---|
| `uuid` | RFC4122，后续所有消息引用它（[schema.json L98-L113](https://github.com/inorbit-ai/ros_amr_interop/blob/main/massrobotics_amr_sender_py/massrobotics_amr_sender/messages/schema.json#L98-L113)） | 机器人全局唯一 ID，比自增主键更适合跨系统 |
| `location.planarDatum` | **map 的 UUID**：`planarDatum` = "Id of planarDatum AMR is referencing"（[L28-L58](https://github.com/inorbit-ai/ros_amr_interop/blob/main/massrobotics_amr_sender_py/massrobotics_amr_sender/messages/schema.json#L28-L58)） | 点位绑地图版本的另一种实现：绑的是**地图 UUID**，不是地图名 |
| `operationalState` | 枚举含 `navigating/idle/charging/waitingHumanEvent/waitingExternalEvent/waitingInternalEvent/manualOverride`（[L235-L250](https://github.com/inorbit-ai/ros_amr_interop/blob/main/massrobotics_amr_sender_py/massrobotics_amr_sender/messages/schema.json#L235-L250)） | **`waitingExternalEvent` 就是"等锁/等电梯"的标准表达**；等资源时车端状态应报这个，而不是假装 navigating |
| `batteryPercentage` / `remainingRunTime` | 0-100 / 小时（[L273-L283](https://github.com/inorbit-ai/ros_amr_interop/blob/main/massrobotics_amr_sender_py/massrobotics_amr_sender/messages/schema.json#L273-L283)） | 充电排队的排序依据 |
| `destinations` / `path` | 最多 10 个预测点（[L298-L315](https://github.com/inorbit-ai/ros_amr_interop/blob/main/massrobotics_amr_sender_py/massrobotics_amr_sender/messages/schema.json#L298-L315)） | 窄道会让时，"对面要去哪"是让行决策的输入；我们没有，只能靠点位/方向推断 |
| `timestamp` | 每条消息必填 | 位姿必须带时间戳，重定位瞬间的跳变才不会被当成漂移 |

### 1.7 轻量替代方案对比（含本机实测）

| 方案 | 原子性来源 | 跨进程 | 跨机 | 崩溃恢复 | 适用规模 | 坑（必读） |
|---|---|---|---|---|---|---|
| **进程内 `asyncio.Lock` + 有序 key** | 单进程内存 | ❌ | ❌ | ❌ 进程重启即丢 | 单 worker（**我们现状**） | 多开一个 uvicorn worker 就失效；重启后要靠 DB 恢复"谁持有" |
| **条件 UPDATE + `rowcount`**（推荐） | 单条 SQL 的行锁 | ✅ | ✅（单库） | ✅ TTL/心跳 | ≤ 数十台、单 DB | 必须一条语句完成"判断+占用"，不能先 SELECT 再 UPDATE |
| **`SELECT ... FOR UPDATE`** | InnoDB 行锁，**持有到 commit** | ✅ | ✅ | ✅ | 同上 | 锁跨网络调用持有 = 长事务 + 连接池被拖死；二级索引可能锁 gap；SQLite **语法直接报错** |
| **MySQL `GET_LOCK()`** | 命名用户锁（MDL） | ✅ | ❌ 单 mysqld | ✅ 会话断开即释放 | 单 MySQL 实例 | **不随 commit/rollback 释放**；连接池复用会"把锁带回来"；名字 ≤64 字符；多把锁可能 `ER_USER_LOCK_DEADLOCK`；获取顺序未定义；语句级复制不安全 |
| **SQLite `BEGIN IMMEDIATE`** | 库级写锁（单写者） | ✅ | ❌ 单文件 | ✅ | 单机、低并发 | 没有 advisory lock；写事务串行；`SQLITE_BUSY` 要 `busy_timeout` 兜 |
| **Redis 单实例 `SET NX PX` + Lua 释放** | 单点 | ✅ | ✅ | ✅ TTL | 多实例 | **没有 fencing token**；主从异步复制会丢锁（官方文档自己列的 SAFETY VIOLATION 场景） |
| **Redlock（5 节点多数派）** | 多数派 | ✅ | ✅ | ✅ TTL | 跨机房 | 依赖"有界网络延迟/有界进程暂停/有界时钟误差"；Kleppmann 的结论是"用于正确性就别用"，Redis 官方页面也补了"应实现 fencing tokens"和"TTL 用的是非单调时钟" |

关键引用：
- MySQL `GET_LOCK`：["Locks obtained with GET_LOCK() are not released when transactions commit or roll back"、"Names are locked on a server-wide basis"、"the order in which they acquire it is undefined"](https://docs.oracle.com/cd/E17952_01/mysql-8.0-en/locking-functions.html)
- MySQL `FOR UPDATE`：["All locks set by FOR SHARE and FOR UPDATE queries are released when the transaction is committed or rolled back"](https://docs.oracle.com/cd/E17952_01/mysql-8.0-en/innodb-locking-reads.html)
- SQLite：["IMMEDIATE causes the database connection to start a new write immediately... might fail with SQLITE_BUSY"、"only one simultaneous write transaction"](https://www.sqlite.org/lang_transaction.html)
- Redis/Redlock：["You should implement fencing tokens"、"Redis is not using monotonic clock for TTL expiration"](https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/)、[Kleppmann《How to do distributed locking》](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)（"it lacks a facility for generating fencing tokens"）

**本机实测（2026-10-27，Python 3.14.2 自带 SQLite）**：

```text
FOR UPDATE: OperationalError near "FOR": syntax error
first acquire rowcount: 1
second acquire rowcount: 0
conn1 holds write txn
conn2 BEGIN IMMEDIATE: OperationalError database is locked
```

→ 结论：**`SELECT ... FOR UPDATE` 在 SQLite 下不可用**，而"条件 UPDATE 看 rowcount"在 SQLite/MySQL 上语义一致。这就是我们选它的硬理由（不是偏好）。

**规模建议（直接照这个决策）**：

| 规模 | 选什么 |
|---|---|
| 1 进程、1-2 台车（现在） | 进程内 `asyncio.Lock` + 有序 key；DB 只存"当前持有者"用于重启恢复和展示 |
| 多 worker / 多实例、单 MySQL | 条件 UPDATE + `rowcount`（**不要**长事务 `FOR UPDATE`） |
| 需要跨机但不跨库、且能接受"锁是近似的" | MySQL `GET_LOCK`（注意连接池） |
| 跨机房/多集群 | etcd/ZooKeeper + **fencing token**；不要 Redlock |

### 1.8 三类资源怎么建模（字段设计）

#### 充电桩排队

| 方案 | 做法 | 依据 | 缺陷 |
|---|---|---|---|
| RMF | **每台车指定专属充电桩**（`charger: "tb3_charger"`），电量低于 `recharge_threshold` 自动插 `ChargeBattery` 任务；"无限期充电"任务在真任务到来时被取消 | [ChargeBattery.hpp L38-L57](https://github.com/open-rmf/rmf_task/blob/main/rmf_task/include/rmf_task/requests/ChargeBattery.hpp#L38-L57)（designated charging waypoint、`recharge_soc`、`indefinite`）；配置 L25-L26、L36 | 专属桩=不需要排队；我们**两台车一个桩**，绕不开 |
| 我们 | `resource_lock` 一行 `charger:{station_id}`（capacity=1）+ `resource_wait` 队列 | — | 需要"低电量插队"的显式规则 |

字段（`resource_lock` + `resource_wait`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `resource_key` | varchar(64) PK | `charger:CS-01` / `lane:L3` / `lift:LIFT-1:2F` |
| `capacity` | smallint | 1=独占；>1 才需要计数（最小版只用 1） |
| `state` | varchar(12) | `free` / `held` / `orphan`（超时待确认） |
| `owner_run_id`, `owner_robot_id` | bigint | 持有者 |
| `fence` | bigint | **每次获得锁 +1**，下发给车端的指令带它；旧 fence 的指令必须被拒 |
| `acquired_at`, `heartbeat_at`, `expires_at` | datetime | TTL/续租 |
| `hold_point_id` | varchar(32) | 窄道用：等的时候停哪个点 |
| `direction` | varchar(8) | 窄道用：`+` / `-`，同向才可共享（最小版仍按独占） |
| 队列表 `resource_wait(resource_key, run_id, robot_id, seq, enqueued_at, state, soc_at_request, priority)` | — | `seq` 单调，FIFO；`priority` 只允许"SOC<20% 插队"一种规则，且写审计 |

#### 窄道会让

| 方案 | 做法 | 依据 |
|---|---|---|
| RMF | 路径上的 `Checkpoint{position, map_name, can_hold}`；`can_hold=false` 的点不能停着等，只能整段独占；`can_hold=true` 的点是会让点/待避点 | [Writer.hpp L37-L48](https://github.com/open-rmf/rmf_traffic/blob/main/rmf_traffic/include/rmf_traffic/blockade/Writer.hpp#L37-L48) |
| 我们 | 窄道 = 一个 `lane:{id}` 独占锁 + `hold_point_id`（进窄道前/窄道内的待避点）+ `direction`；对面来车时，**只允许已持有者前进，另一方退到 hold_point**（不是"谁先谁过"，是"谁已经在里面谁先出"） | 这是 RMF `can_hold` 的最小化：没有 hold point 的窄道，**根本不该允许两台车同时进入** |

#### 电梯占用

| 方案 | 做法 | 依据 |
|---|---|---|
| RMF | 电梯是 4 个事件组成的会话：`LiftSessionBegin`（进梯）→ `LiftMove`（移动）→ `LiftDoorOpen`（开门）→ `LiftSessionEnd`（出梯）；每步带 `(lift_name, floor_name, duration)` | [Graph.hpp L392-L456](https://github.com/open-rmf/rmf_traffic/blob/main/rmf_traffic/include/rmf_traffic/agv/Graph.hpp#L392-L456) |
| VDA5050 | 电梯是**跨图**：出梯后"从出发层地图消失、在目标层地图的电梯节点出现"，两张图 `mapId` 不同、原点一致 | [VDA5050_EN.md L1498](https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md#L1498)、[L1814](https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md#L1814) |
| 我们 | `lift:{lift_id}` 独占 + 状态机字段，而不是纯锁 | — |

电梯字段（建议放在 `resource_lock` 的扩展表 `lift_state`，不要塞进锁表）：

```text
lift_state(
  lift_id PK,
  current_floor, target_floor,
  door_state ENUM('closed','opening','open','closing'),
  session_run_id, session_robot_id,
  updated_at, source           -- source: adapter 上报 / 平台推断
)
```

**关键**：电梯不是"抢到锁就能用"，是"抢到锁 + 电梯在该层 + 门开着"三个条件。只用一把锁会造出"锁在我手里、电梯在 5 楼"的死等。

---

## 2. 二、定位初始化 / 重定位

### 2.1 Nav2 AMCL：`/initialpose` 到底做了什么

**调用时机**（按代码顺序）：

| 时机 | 行为 | 代码 |
|---|---|---|
| 启动且 `set_initial_pose=true` | 用 `initial_pose.x/y/z/yaw` 参数直接置位 | [L108-L126](https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/src/amcl_node.cpp#L108-L126)、参数声明 [L968-L972](https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/src/amcl_node.cpp#L968-L972) |
| 收到 `/initialpose` 但节点未 active | 只缓存，等 active 后处理 | [L434-L444](https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/src/amcl_node.cpp#L434-L444) |
| 收到 `/initialpose` | ①校验消息 ②**frame_id 必须是 `map`**，否则丢弃 ③点位在栅格地图外则拒绝 ④把 `msg.header.stamp` 到"现在"的 odom 增量乘上去 ⑤`pf_init(mean, cov)` | [L405-L431](https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/src/amcl_node.cpp#L405-L431)、[L447-L509](https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/src/amcl_node.cpp#L447-L509) |
| 不知道在哪 | 调 `reinitialize_global_localization`：在自由空间均匀撒粒子 | [L362-L382](https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/src/amcl_node.cpp#L362-L382) |
| 需要立刻出结果 | 调 `request_nomotion_update`：强制一次更新，**不用等车动** | [L394-L402](https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/src/amcl_node.cpp#L394-L402) |

**服务清单（名字容易记错）**：

| 服务 | 类型 | 作用 |
|---|---|---|
| `/reinitialize_global_localization` | `std_srvs/Empty` | 全局重定位（均匀撒粒子） |
| `/set_initial_pose` | `nav2_msgs/SetInitialPose`（= `PoseWithCovarianceStamped`） | 与 `/initialpose` 同义，服务版 |
| `/request_nomotion_update` | `std_srvs/Empty` | 强制更新一次（校验时必用） |

代码：[L1450-L1470](https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/src/amcl_node.cpp#L1450-L1470)、[SetInitialPose.srv](https://github.com/ros-navigation/navigation2/blob/main/nav2_msgs/srv/SetInitialPose.srv)。

**covariance 怎么填**：

AMCL 只读这 5 个位置（`i,j∈{0,1}` 的 3×3 块 + yaw）：

```cpp
for (int i = 0; i < 2; i++)
  for (int j = 0; j < 2; j++)
    pf_init_pose_cov.m[i][j] = msg.pose.covariance[6 * i + j];
pf_init_pose_cov.m[2][2] = msg.pose.covariance[6 * 5 + 5];   // yaw = index 35
```

→ 正确填法（其余全 0 没关系）：

```python
cov = [0.0] * 36
cov[0]  = 0.25   # x 方差：σ=0.5 m
cov[7]  = 0.25   # y 方差
cov[35] = 0.0685 # yaw 方差：(π/12)^2 ≈ 0.0685，σ≈15°
# 若点位很准（贴地标）：x/y 用 0.05^2，yaw 用 (3°)^2
```

依据：AMCL 在"完全不知道"时兜底用的就是 `0.5², 0.5², (π/12)²`（[L1483-L1486](https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/src/amcl_node.cpp#L1483-L1486)）。**先验给 0.5 m/15°、目标点给 0.3 m/3°，是同一套语义的两端**，不是拍脑袋。

**默认参数（`nav2_bringup/params/nav2_params.yaml`，建议照抄再改）**：

| 参数 | 默认 | 含义/注意 |
|---|---|---|
| `transform_tolerance` | 1.0 s | TF 时间戳容忍；**这也是我们判"TF 超时"的阈值**（[L33](https://github.com/ros-navigation/navigation2/blob/main/nav2_bringup/params/nav2_params.yaml#L33)） |
| `update_min_d` / `update_min_a` | 0.25 m / 0.2 rad | 走这么远/转这么多才更新一次滤波（[L35-L36](https://github.com/ros-navigation/navigation2/blob/main/nav2_bringup/params/nav2_params.yaml#L35-L36)） |
| `max_particles` / `min_particles` | 2000 / 500 | 粒子数（[L20-L21](https://github.com/ros-navigation/navigation2/blob/main/nav2_bringup/params/nav2_params.yaml#L20-L21)） |
| `save_pose_rate` | 0.5 Hz | 位姿落盘频率（[L30](https://github.com/ros-navigation/navigation2/blob/main/nav2_bringup/params/nav2_params.yaml#L30)） |
| `recovery_alpha_slow` / `fast` | **0.0 / 0.0** | **默认关闭随机粒子注入** → AMCL 不会自己从"被搬走"里恢复，必须外部触发全局重定位（[L25-L26](https://github.com/ros-navigation/navigation2/blob/main/nav2_bringup/params/nav2_params.yaml#L25-L26)） |
| `first_map_only` | false | 收到新地图会**替换**（但不重置位姿，见 2.3） |
| `always_reset_initial_pose` | false | 重启后是否清空"已知位姿" |

### 2.2 slam_toolbox：纠正三个常见误解

| 误解 | 代码事实 | 正确做法 |
|---|---|---|
| "调 `/slam_toolbox/set_pose` 重定位" | 全仓**没有**这个服务。服务只有：`dynamic_map`(GetMap)、`pause_new_measurements`、`serialize_map`、`deserialize_map`、`clear_localization_buffer`、`save_map`（[common.cpp L224-L239](https://github.com/SteveMacenski/slam_toolbox/blob/humble/src/slam_toolbox_common.cpp#L224-L239)、[README L186-L192](https://github.com/SteveMacenski/slam_toolbox/blob/humble/README.md#L186-L192)） | 用 `/initialpose`（localization 模式）或 `/slam_toolbox/deserialize_map` |
| "`/initialpose` 的 covariance 会被用到" | `localizePoseCallback` 只取 `position.x/y` 和 `yaw`，**covariance 一行都没读**（[L209-L239](https://github.com/SteveMacenski/slam_toolbox/blob/humble/src/slam_toolbox_localization.cpp#L209-L239)） | 别指望用 covariance 表达"我有多确定" |
| "slam_toolbox 是 lifecycle 节点，要用 lifecycle_manager 管" | `class SlamToolbox : public rclcpp::Node`（[slam_toolbox_common.hpp L59](https://github.com/SteveMacenski/slam_toolbox/blob/humble/include/slam_toolbox/slam_toolbox_common.hpp#L59)）；服务/订阅在**构造函数**里建（`setROSInterfaces()`，[common.cpp L56](https://github.com/SteveMacenski/slam_toolbox/blob/humble/src/slam_toolbox_common.cpp#L56)） | 没有 configure/activate 门；就绪判断只能靠"服务能不能调通 / `/map` 有没有数据" |

**重定位的真实入口**（localization 模式）：

```text
# 方式 A：给先验（covariance 被忽略）
ros2 topic pub --once /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
  '{header: {frame_id: "map", stamp: {sec: 0, nanosec: 0}}, pose: {pose: {position: {x: 1.0, y: 2.0}, orientation: {z: 0.0, w: 1.0}}}}'
# 注意：stamp 填 0 表示"最新"，不要填一个旧时间（slam_toolbox 不做 odom 补偿，但下游融合可能做）

# 方式 B：加载位姿图并指定初始位姿（唯一能在"不知道在哪"时用的）
ros2 service call /slam_toolbox/deserialize_map slam_toolbox/srv/DeserializePoseGraph \
  "{filename: '/maps/site1', match_type: 3, initial_pose: {x: 1.0, y: 2.0, theta: 0.0}}"
# match_type: 1=START_AT_FIRST_NODE, 2=START_AT_GIVEN_POSE, 3=LOCALIZE_AT_POSE
```

依据：[DeserializePoseGraph.srv L1-L11](https://github.com/SteveMacenski/slam_toolbox/blob/humble/srv/DeserializePoseGraph.srv#L1-L11)；localization 模式只接受 `LOCALIZE_AT_POSE`，其它返回 false（[L102-L113](https://github.com/SteveMacenski/slam_toolbox/blob/humble/src/slam_toolbox_localization.cpp#L102-L113)）；非 localization 模式收到 `/initialpose` 直接报错忽略（[L214-L219](https://github.com/SteveMacenski/slam_toolbox/blob/humble/src/slam_toolbox_localization.cpp#L214-L219)）。

**在 localization 模式下不可用的东西**（很容易踩）：

```cpp
// 构造时就把 map saver 关了
map_saver_.reset();                       // L45-L46
// serialize 直接返回错误
RCLCPP_ERROR(..., "Cannot call serialize map in localization mode!");  // L90-L99
```

→ **`/slam_toolbox/save_map` 和 `/slam_toolbox/serialize_map` 在 localization 模式下都不可用**。建图/存图必须在 mapping 模式做完，再切 localization。`save_map` 存的是 PGM+YAML（给 AMCL 用），`serialize_map` 存的是 posegraph（给 slam_toolbox 自己用），**两者不能互相替代**。

### 2.3 多地图：`map_server` 动态加载 + 点位绑地图版本

#### `/map_server/load_map` 的真实行为

| 事实 | 代码 |
|---|---|
| 服务名是 `load_map`，节点名 `map_server` → 全名 `/map_server/load_map`；另有 `/map_server/map`(GetMap) | [map_server.hpp L122-L132](https://github.com/ros-navigation/navigation2/blob/main/nav2_map_server/include/nav2_map_server/map_server.hpp#L122-L132) |
| `map_url` 支持 `file:///...` 和 `package://...` | [LoadMap.srv L1-L4](https://github.com/ros-navigation/navigation2/blob/main/nav2_msgs/srv/LoadMap.srv#L1-L4) |
| **节点不在 ACTIVE 状态时直接忽略**，返回 `RESULT_UNDEFINED_FAILURE` | [map_server.cpp L195-L207](https://github.com/ros-navigation/navigation2/blob/main/nav2_map_server/src/map_server/map_server.cpp#L195-L207) |
| 加载成功后**主动 publish 一次**（transient_local，等价 ROS1 latched），AMCL 会收到 | [L208-L213](https://github.com/ros-navigation/navigation2/blob/main/nav2_map_server/src/map_server/map_server.cpp#L208-L213)、publisher [L114-L117](https://github.com/ros-navigation/navigation2/blob/main/nav2_map_server/src/map_server/map_server.cpp#L114-L117) |
| 结果码：`RESULT_SUCCESS=0 / MAP_DOES_NOT_EXIST=1 / INVALID_MAP_DATA=2 / INVALID_MAP_METADATA=3 / UNDEFINED=255` | [LoadMap.srv L6-L15](https://github.com/ros-navigation/navigation2/blob/main/nav2_msgs/srv/LoadMap.srv#L6-L15) |
| `yaml_filename` 可为空，此时启动后等 `load_map` 服务 | [L90-L104](https://github.com/ros-navigation/navigation2/blob/main/nav2_map_server/src/map_server/map_server.cpp#L90-L104) |
| 换图会刷新 `info.map_load_time` | [L242-L244](https://github.com/ros-navigation/navigation2/blob/main/nav2_map_server/src/map_server/map_server.cpp#L242-L244) |

**换图后 AMCL 不会自动重置**（这是最容易翻车的一步）：

```cpp
void AmclNode::handleMapMessage(const nav_msgs::msg::OccupancyGrid & msg) {
  ...
  freeMapDependentMemory();     // 只释放 map_ 和排队中的 laser
  map_ = convertMap(msg);       // 换新图
}                               // initial_pose_is_known_ / pf_ 都没动
```

依据：[L1300-L1322](https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/src/amcl_node.cpp#L1300-L1322)、[freeMapDependentMemory L1341-L1353](https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/src/amcl_node.cpp#L1341-L1353)。而 `first_map_only` 默认 false（[L997](https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/src/amcl_node.cpp#L997)），所以"新图会被接受，但位姿还是旧图的"——**必须紧接着 reinit/initialpose + 校验**。

正确的换图时序：

```text
1. 停任务、等车停稳（速度≈0 持续 2 s）
2. ros2 service call /map_server/load_map nav2_msgs/srv/LoadMap "{map_url: 'file:///maps/site2.yaml'}"
   → 检查 result == 0，并读回 /map_server/map 的 info.map_load_time / 分辨率 / 尺寸
3. 清 AMCL：/reinitialize_global_localization（或直接 /set_initial_pose 给已知点）
4. 发 /initialpose（stamp=now，cov 见 2.1）
5. /request_nomotion_update + 校验（见 2.6）
6. 校验不通过：任务保持 paused，告警，不自动重试超过 1 次
```

#### 点位绑地图版本：三个开源实现给的三种字段

| 实现 | 字段 | 语义 | 强度 |
|---|---|---|---|
| VDA5050 | `nodePosition.mapId` + 订单里的 `mapId`；`maps[]` 里 `{mapId, mapVersion, mapStatus}` | 每个 map 有 `mapId` + `mapVersion`；同一 `mapId` 同时只能有一个 version 是 `ENABLED`；缺失报 `UNKNOWN_MAP_ID`(WARNING) | **强**：订单/节点/状态三处都带 |
| VDA5050 | `initializePosition` 动作参数 `x, y, theta, mapId, lastNodeId` | 换图后初始化位姿必须显式带 `mapId`；状态回传同样带 | **强** |
| MassRobotics | `location.planarDatum` = 地图 UUID | 位姿绑的是地图 UUID，不是名字 | 中（只绑位姿，不绑点位） |
| Nav2 | 无内建版本；`map_url` 就是唯一标识 | 靠文件名/路径约定 | **弱** |

原文：[VDA5050_EN.md L801-L803](https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md#L801-L803)（mapId+mapVersion、UNKNOWN_MAP_ID）、[L816-L817](https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md#L816-L817)（maps[] 状态）、[L714-L717](https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md#L714-L717)（initializePosition/enableMap/downloadMap 参数）、[L1810-L1817](https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md#L1810-L1817)（状态里的 `mapId`）。

**我们现状**：`PlatformMap` 只有 `name/floor/station/resolution/origin_*/robot_map_name`，**没有版本号**；`PointDraft.map_id` 是自增主键外键（[map_library.py L21-L59](../../server/app/models/map_library.py#L21-L59)）。重建图那天，所有点位坐标会静默失效。

最小改法（不大动）：

| 表 | 新增字段 | 说明 |
|---|---|---|
| `platform_map` | `map_version varchar(16)`、`map_checksum varchar(64)` | 每次重建图 +1；checksum 是 PGM+YAML 的 SHA256，用于"机器人上的图到底是不是这张" |
| `point_draft` | `map_version varchar(16)` | 与 `map_id` 联合确定"这个坐标属于哪版图" |
| `task_run_step.result_json` | `map_id` + `map_version` | 到点偏差只有在同一地图版本下才可比 |

不做全量迁移（当前只有 1 张图），但字段先加、下发订单时带上——这跟 VDA5050 的 `mapVersion` 是同一件事。

### 2.4 RTK / 融合定位：质量字段怎么用

**先纠正一个前提**：`fibo_fusion_pose` **不是公开 ROS 生态里的标准 topic**。2026-10-27 用公开检索找不到同名消息定义/仓库；按命名推断是厂商或项目自定义的融合定位输出。所以下面给的是"**不管字段叫什么，判据必须是这几项**"的消费契约，而不是对某个包的断言。

融合/RTK 类输出的通用质量语义（用 VDA5050 做锚）：

| 字段 | 规范定义 | 能不能用来做"该不该重定位" |
|---|---|---|
| `localized` (bool) | "false: x/y/theta cannot be trusted... shall not resume automatic driving"，且必须报 `LOCALIZATION_ERROR`(FATAL) | ✅ **唯一权威判据** |
| `localizationScore` (0..1) | "Describes the quality of the localization... **Only for logging and visualization purposes**" | ❌ 不能单独做安全门；只能做趋势/降级 |
| `deviationRange` (m) | "Value for the deviation range of the position in meters. Only for logging and visualization purposes." | ⚠️ 可做"到点存疑"的辅助，不能单独判丢失 |
| `positionInitialized` / `location_status` | 底盘自己报"我定了没" | ✅ 与 `localized` 同级 |

原文：[VDA5050_EN.md L1815-L1817](https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md#L1815-L1817)；FATAL 语义 [L1126](https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md#L1126)、[L1174](https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md#L1174)。

**厂商私有 topic 的消费契约**（建议写进适配器，字段缺失就降级）：

```python
# 归一化：任何融合定位消息 -> 平台内部结构
{
  "x": float, "y": float, "yaw": float,
  "stamp": float,            # 必须；没有就用收到的时间并标 stale
  "map_id": str,             # 必须；没有就无法和多地图对齐
  "located": bool | None,    # 硬门（缺失=None，按"未知"处理，不当 True）
  "quality": float | None,   # 0..1，仅趋势
  "deviation_m": float | None,
  "source": "amcl" | "slam_toolbox" | "rtk" | "fusion",
}
```

判据（这是我们的工程规则，标注为经验值）：
- `located is False` 或 `location_status == 1` → 进入"丢失"流程；
- `quality` 连续 5 帧 < 0.5 → 降级（限速/禁窄道），**不直接重定位**；
- `deviation_m > 0.5 × arrive_radius` → 该点判 `arrived_suspect`，不判失败；
- RTK 的 fix 类型（fixed/float/single）应映射进 `quality`：`fixed→0.9`、`float→0.6`、`single→0.3`、`no fix→located=False`。**这一步必须做**，否则 RTK 失锁时 quality 还很高。

### 2.5 "定位丢失"的信号与阈值（分清规范/代码默认/经验值）

| 信号 | 取值 | 建议阈值 | 来源性质 |
|---|---|---|---|
| `/location_status`（X30） | `0` 正常 / `1` 丢失 | **连续 10 s（≥3 帧）为 1 → LOST** | 厂商协议（[adapter.py L69](../../server/app/adapters/deeprobotics/adapter.py#L69)、[alarms.py L164](../../server/app/services/alarms.py#L164)）；10 s 是经验值 |
| `localized`（VDA5050/融合） | bool | `false` 即时降级；持续 3 s → LOST | 规范强制（L1815-L1817） |
| AMCL 协方差 σx/σy | m | `> 0.5` → DEGRADED；`> 1.0` → LOST | 代码默认先验 0.5 m（L1483-L1486），阈值由此推导 |
| AMCL 协方差 σyaw | rad | `> 0.26`(15°) → DEGRADED | 同上（π/12） |
| 扫描匹配 response（Karto） | 0..1 | link 匹配 `< 0.1` 不接受；loop 闭环 coarse `< 0.35`、fine `< 0.45` | **slam_toolbox 建图默认参数**（[mapper_params_localization.yaml L41-L47](https://github.com/SteveMacenski/slam_toolbox/blob/humble/config/mapper_params_localization.yaml#L41-L47)），不是定位模式阈值 |
| TF `map→base_link` 年龄 | s | `> 1.0` 视为断 | AMCL `transform_tolerance` 默认 1.0（params L33）；free_fleet 取不到 TF 直接不更新（nav2_robot_adapter L315-L341） |
| 相邻帧位姿跳变 | m/帧 | `> 0.5` 且 odom 无对应变化 → suspect | 经验值（重定位/漂移的特征） |
| 到点残差 | m | `> 1.0×半径` → suspect；`> 2.5×半径` → failed | 本项目巡航判定（`docs/巡航与任务下发-改造规划.md` 改动 C） |
| 粒子云离散度 | m | 加权 σ > 0.5 → DEGRADED | 经验值；AMCL 发布 `/particle_cloud`（[amcl_node.cpp L1430-L1432](https://github.com/ros-navigation/navigation2/blob/main/nav2_amcl/src/amcl_node.cpp#L1430-L1432)），可自己算 |

> **两条硬规则**：①**单帧不触发重定位**，至少连续 3 帧；②**运动中不重定位**——先减速停车（速度≈0 持续 2 s），再重定位。腿式机器人运动中重定位会让规划器甩出高速修正路径，窄道里直接撞（这条与 `docs/reviews/model_review_20261027-173507.md` 的结论一致）。

### 2.6 初始化后怎么验证位姿真的对

**先说结论：读回一致 ≠ 定位正确**。`/initialpose` 之后读到的 `amcl_pose` 之所以等于你给的值，是因为粒子就是按你给的值撒的——这只证明"设置生效"，不证明"你给对了"。真正有效的验证是三层：

| 层 | 验什么 | 怎么验 |
|---|---|---|
| L1 生效 | 设置有没有被接受 | `amcl_pose` 新帧与给定值差 ≤ 0.5 m / 15° |
| L2 收敛 | 滤波器有没有收敛 | 连续 3 帧协方差 ≤ 先验；`/particle_cloud` 离散度下降 |
| L3 自洽 | 位姿和现实是否一致 | 直行 1 m，比较 **map 增量 vs odom 增量**：`abs(Δmap − Δodom) ≤ 0.2 m`、航向差 ≤ 5°；或对已知地标（充电桩/反光板）测距 |

L3 是唯一能发现"给错楼层/给错点位"的检查。1 m 太短可以走 2 m，但**必须在空旷直道**做，且失败只告警不自动重试。

---

## 附录 A：核对清单（2026-10-27 快照）

| 仓库 | 分支 | 文件 | 用途 |
|---|---|---|---|
| open-rmf/rmf_traffic | main | `rmf_traffic/include/rmf_traffic/agv/Graph.hpp` | Door/LiftSession/Dock/Wait 字段 |
| open-rmf/rmf_traffic | main | `rmf_traffic/include/rmf_traffic/blockade/{Writer,Moderator,Participant}.hpp` | 预约/区间/gridlock/cancel |
| open-rmf/rmf_traffic | main | `rmf_traffic/src/rmf_traffic/blockade/{Constraint,Moderator}.cpp` | 环检测实现 |
| open-rmf/rmf_traffic | main | `rmf_traffic/include/rmf_traffic/schedule/{Participant,Negotiation}.hpp` | 日程/协商 API |
| open-rmf/rmf_task | main | `rmf_task/include/rmf_task/{Task,BinaryPriorityScheme}.hpp` | 三档语义/优先级 |
| open-rmf/rmf_task | main | `rmf_task/include/rmf_task/requests/ChargeBattery.hpp` | 充电任务模型 |
| open-rmf/free_fleet | main | `free_fleet_adapter/free_fleet_adapter/{fleet_adapter,nav2_robot_adapter}.py` | 多机接入/换图 TODO |
| open-rmf/free_fleet | main | `free_fleet_examples/config/fleet/nav2_tb3_simulation_fleet_config.yaml` | 最小配置契约 |
| inorbit-ai/ros_amr_interop | main | `massrobotics_amr_sender_py/.../messages/schema.json` | 状态契约/planarDatum |
| ros-navigation/navigation2 | main | `nav2_amcl/src/amcl_node.cpp` | initialpose/协方差/服务 |
| ros-navigation/navigation2 | main | `nav2_msgs/srv/{LoadMap,SetInitialPose}.srv` | 服务类型 |
| ros-navigation/navigation2 | main | `nav2_map_server/src/map_server/map_server.cpp` | load_map 行为 |
| ros-navigation/navigation2 | main | `nav2_bringup/params/nav2_params.yaml` | AMCL 默认参数 |
| SteveMacenski/slam_toolbox | humble | `src/slam_toolbox_{common,localization}.cpp`、`srv/DeserializePoseGraph.srv`、`config/mapper_params_localization.yaml` | 重定位/服务/阈值 |
| VDA5050/VDA5050 | main | `VDA5050_EN.md`、`json_schemas/state.schema` | mapId/agvPosition/错误等级 |

## 附录 B：没核对到的（别当成结论用）

- **rmf_ros2 的调度节点**（`Negotiation` 的超时/放弃策略）：本机到 GitHub 的网络不稳定，`rmf_traffic` 库本身**没有** deadline（已核对），但 ROS2 调度节点是否在外层加超时**未核对**。
- **RMF building map 的 `is_charger` 标注**：本次没有拉 `rmf_building_map_tools`，充电桩建模结论基于 `ChargeBattery` 的 `charging_waypoint` 与 free_fleet 的 `charger:` 配置。
- **X30 的 2101 与 ROS `/initialpose` 的相互关系**（谁覆盖谁、是否需要双发）：厂商文档未给，必须真机做矩阵测试（冷启动/热重启/丢定位/拖走各 10 次）。
- **`fibo_fusion_pose`**：公开检索无同名消息定义，字段以现场 `ros2 interface show` + `ros2 topic echo` 为准。

---

## 3. 给我们的最小方案

### 3.1 `resource_lock` 表（MySQL/SQLite 通用）

```sql
CREATE TABLE resource_lock (
  resource_key   VARCHAR(64) PRIMARY KEY,   -- charger:CS-01 / lane:L3 / lift:LIFT-1:2F / door:D2
  kind           VARCHAR(16) NOT NULL,      -- charger|lane|lift|door|dock
  capacity       SMALLINT NOT NULL DEFAULT 1,
  state          VARCHAR(12) NOT NULL DEFAULT 'free',  -- free|held|orphan
  owner_run_id   BIGINT NULL,
  owner_robot_id BIGINT NULL,
  fence          BIGINT NOT NULL DEFAULT 0, -- 每次获得 +1；下发给车端的指令带它
  hold_point_id  VARCHAR(32) NULL,          -- 窄道会让点
  direction      VARCHAR(8)  NULL,          -- 窄道方向 '+/-'
  acquired_at    DATETIME NULL,
  heartbeat_at   DATETIME NULL,
  expires_at     DATETIME NULL,
  note           VARCHAR(200) NULL
);

CREATE TABLE resource_wait (           -- 排队/审计；不参与互斥判定
  id BIGINT PRIMARY KEY,
  resource_key VARCHAR(64) NOT NULL,
  run_id BIGINT NOT NULL,
  robot_id BIGINT NOT NULL,
  seq BIGINT NOT NULL,                -- 单调，FIFO
  enqueued_at DATETIME NOT NULL,
  state VARCHAR(12) NOT NULL DEFAULT 'waiting',  -- waiting|granted|cancelled|timeout
  soc_at_request FLOAT NULL,
  priority SMALLINT NOT NULL DEFAULT 0
);
```

### 3.2 抢锁（一条 SQL 定胜负，按 key 字典序，失败即全放）

```python
# 伪代码：SQLAlchemy Session，同步（与现有 db/session.py 一致）
def acquire(db, keys: list[str], run_id: int, robot_id: int, ttl_s: int = 90) -> bool:
    keys = sorted(set(keys))                      # ① 全局顺序，消灭环路等待
    now = datetime.now()
    exp = now + timedelta(seconds=ttl_s)          # ② 时间在 Python 算，SQL 两端通用
    got = []
    for k in keys:
        r = db.execute(text("""
            UPDATE resource_lock
               SET state='held', owner_run_id=:run, owner_robot_id=:robot,
                   fence=fence+1, acquired_at=:now, heartbeat_at=:now, expires_at=:exp
             WHERE resource_key=:k
               AND (state='free' OR expires_at < :now OR owner_run_id=:run)
        """), {"k": k, "run": run_id, "robot": robot_id, "now": now, "exp": exp})
        if r.rowcount != 1:                        # ③ 一条语句完成"判断+占用"
            db.rollback()                          # ④ 不 hold-and-wait
            return False
        got.append(k)
    db.commit()                                    # ⑤ 事务只包 UPDATE，不包网络调用
    return True
```

- **为什么不是 `SELECT FOR UPDATE`**：锁会持有到 commit，中间一旦发 HTTP 给车端就是长事务；且 SQLite 不支持（本机实测语法错误）。条件 UPDATE 的原子性由单条语句保证，SQLite/MySQL 行为一致。
- **`rowcount` 是唯一判据**，不要 `SELECT` 后再判断。
- **`owner_run_id=:run` 允许重入**（同一任务重试不会自己锁死自己）。

### 3.3 TTL / 续租 / 死锁兜底

| 机制 | 取值 | 规则 |
|---|---|---|
| 心跳 | 15 s | 巡航线程每步开始 `UPDATE ... SET heartbeat_at=now, expires_at=now+90s WHERE resource_key=? AND owner_run_id=?`；`rowcount=0` → **立刻中止任务**（锁已丢，fence 已过期） |
| TTL | 90 s | 必须 > 单条指令最长耗时（X30 1003 是长阻塞，取值要按实测）|
| 超时回收 | 每 10 s | `expires_at < now` → `state='orphan'` + 告警；**不立刻给别人**，等 60 s 且该车遥测显示 idle/速度≈0，才置 `free` |
| 死锁检测 | 每 10 s | 用 `resource_lock` + `resource_wait` 建 wait-for 图，找环；有环 → 中止环上 `run_id` 最大（最年轻）的那个任务并释放其锁（RMF 的"环检测"最小化版） |
| 强制释放 | 人工/任务终态 | `finally` 里释放；`takeover()` 时一并释放该车所有锁 |
| fencing | `fence` | 每条下发指令带 `(resource_key, fence)`；网关/适配器拒绝 `fence` 小于已见值的指令（防"暂停的线程醒来继续开"） |

### 3.4 重定位触发条件表

| 触发 | 判据（可直接实现） | 动作 |
|---|---|---|
| 开机首连 | 连上后 `located=false` 连续 3 帧 | 横幅"请确认定位"，**不自动发** |
| 运行中丢失 | `location_status==1` 或 `localized=false` 持续 ≥10 s，且速度≈0 持续 2 s | 暂停任务 → 全局重定位/人工先验 |
| 到点存疑 | `arrived_suspect`（1.0 < 残差 ≤ 2.5 m） | 暂停 → 重定位 → 复评该点（最多重试 1 次） |
| 协方差发散 | σx/σy > 0.5 m 或 σyaw > 15°，连续 5 帧 | 降级（限速/禁窄道）+ 建议重定位 |
| 位姿跳变 | 相邻帧 map 位姿 Δ>0.5 m 且 odom 无对应 | 标 suspect，等下一帧确认 |
| 切图/换层 | `map_id`/`map_version` 变化 | load_map → reinit → initialpose → 校验 |
| 被搬动 | **只看 `located=false`**，不看 odom 位移 | 同"运行中丢失" |
| 重建图后 | `platform_map.map_version` 变化 | 点位迁移 + 全部强制重定位一次 |

### 3.5 初始化后校验（10 步，发完 `/initialpose` 按顺序执行；任一步失败即判"初始化未通过"）

1. 读 `/map_server/map` 的 `info.map_load_time` + 尺寸 + 分辨率，确认是期望地图（换图后必须重做）。
2. 确认 `map→odom→base_link` TF 存在且年龄 < 1.0 s（AMCL `transform_tolerance`）。
3. 发 `/initialpose`：`frame_id="map"`，`stamp=now`，`cov[0]=cov[7]=0.25`，`cov[35]=0.0685`。
4. 调 `/request_nomotion_update`（`std_srvs/Empty`），强制产生一次更新，不用等车动。
5. 等 `amcl_pose` 中 `stamp >` 发布时刻的**第一帧**（否则读到的是旧位姿）。
6. 比对 `|Δx|,|Δy| ≤ 0.5 m`、`|Δyaw| ≤ 15°`（与 AMCL 自身默认先验一致）。
7. 连续 3 帧 `cov[0] ≤ 0.25`、`cov[7] ≤ 0.25`、`cov[35] ≤ 0.0685`（协方差收敛）。
8. X30 通道：2101 后读 1002 的 `Location==1` 连续 3 帧（**与步骤 3 二选一，不许双发**）。
9. 直行 1 m：`|Δmap − Δodom| ≤ 0.2 m` 且航向差 ≤ 5°，否则判失败。
10. 通过 → 写审计 + 允许下发；失败 → 保持暂停 + 告警，最多自动重试 1 次。

---

## 4. 明确不做

1. **RMF 的 Negotiation/Table 协商**：`reject` 要求车端能给 alternatives（改道/让行），X30/JCROB 都没有 pause，做了只会互相拒绝到超时。
2. **RMF blockade 全域路网**：我们没路网、没轨迹登记；只借"预约 + `can_hold` + 环检测"三个思想，不引入 `rmf_traffic`。
3. **Redlock / Redis**：单机单 worker 用不上；且 Redlock 无 fencing token、TTL 用非单调时钟，官方自己都建议补 fencing。
4. **自动重定位**：腿式机器人运动中重定位会让姿态/规划崩，只做"停稳 + 提示 + 人确认 + 一次性自动重试"。
5. **`localizationScore` 当安全门**：规范明说只用于日志/可视化；只用 `localized`/`location_status`。
6. **用 odom 位移判"被搬动"**：腿式里程计漂移大（抱起来走 5 m，odom 可能跳 10 m），只看底盘 `located`。
7. **VDA5050 全量**（node/edge/base-horizon）：我们逐点下发，没有"边"；只借 `orderId+updateId` 幂等与 `mapId+mapVersion`。
8. **点位绑地图版本的全量迁移**：当前只有 1 张图，先加 `map_version`/`map_checksum` 字段并在订单里带上，不做历史点位迁移。

---

