# 请评审我们的改造方案（巡航/下发/多机/定位），挑出会翻车的地方

你是"既写过 VDA5050 适配器、又接过 Open-RMF、还踩过机器狗现场坑"的资深工程师。
下面是我们准备实施的方案草稿。请**逐条挑毛病**，尤其指出"看起来对、实际会翻车"的细节，
并给出你认为更好的做法（可以引用开源实现，给仓库/文件）。

## 现状（真实，别假设）
- FastAPI + SQLAlchemy + MySQL/SQLite 单机部署，单 uvicorn worker
- TaskRun 表：status ∈ {planned, running, done, failed, cancelled}；external_id 普通索引
- 下发：`orderId = JC-{毫秒}`（每次调用都变）；整单（JCROB sub_tasks）与逐点（X30 1003）两条链路并存
- 巡航：平台逐点 goto → 轮询订单状态（1007 / HTTP）→ 判到达（距离 ≤ 1m，240s 超时）→ 动作 → 下一点
- 多机：只有"一车一任务"前置检查（assert_free），无资源互斥
- 定位：X30 支持 2101 重置定位 + /initialpose（ROS）+ /location_status（0 正常/1 丢失）；我们只做了手工按钮
- 现场：一台 X30 机器狗 + 一台 JCROB 轮式（真机未到）；厂区有窄道、充电桩

## 方案草稿

### P0-1 订单幂等
- 新增字段：`order_key`（唯一索引）、`attempt`（int）
- 生成规则：`order_key = f"run-{run_id}-a{attempt}"`；同一 run 重发时 attempt+1
- 下发前先查 `TaskRun.external_id` 是否已有值，有就拒绝重复下发
- 车端返回的任务 id 写入 `external_id`，重复上报按 external_id upsert

### P0-2 exec_mode（能力协商）
- 适配器新增类属性 `exec_mode: "order" | "waypoint"`（JCROB=order，X30=waypoint）
- 平台：order 模式一次发整条 sub_tasks；waypoint 模式仍逐点
- 巡航逻辑统一为：`if adapter.exec_mode == "order": 发整单并轮询；else: 逐点`

### P0-3 状态机
- 扩为 7 态：planned → dispatched → accepted → running → paused → done/failed/cancelled
- 规则：调用下发成功=dispatched；车端首次回报=accepted；有进度=running
- 所有状态变更写 audit

### P0-4 到点三值判定
- 结果：`arrived` / `arrived_suspect` / `failed`
- arrived：导航状态 FINISHED 且距离 ≤ 1.0m 且速度 < 0.05m/s
- arrived_suspect：FINISHED 但 1.0m < 距离 ≤ 2.5m（不重试，提示重定位）
- failed：超时 / 导航失败 / 距离 > 2.5m
- arrived_suspect 时把该点状态记为 `suspect`，并产生一条"定位疑似漂移"告警

### P1-5 资源锁
- 表 `resource_lock(resource_key PK, run_id, robot_id, acquired_at, ttl_s, note)`
- 抢锁：对需要的一组 key 排序后逐个 `INSERT`，任一冲突就整体回滚
- TTL 60s 续租，进程退出用 finally 释放；每 15s 扫过期锁

### P1-6 定位策略
- 触发重定位：断电重启后首次连上、`located=false` 持续 10s、切图、被搬动（odom 位移 > 5m 但定位未更新）
- 重定位后校验：读回 pose，与目标误差 < 0.5m 且 3 秒内 `located=true`，否则告警

## 请回答
1. 这 6 条里哪几条"实现出来会翻车"？逐条说清触发条件和后果。
2. `order_key` 用 `run-{id}-a{n}` 有什么问题？更稳的生成方式是什么？
3. 7 态状态机是否够用/多余？有没有更简单的等价方案（我们单 worker、无消息队列）？
4. 到点判定只加"速度"够吗？还需要什么信号？`arrived_suspect` 会不会变成"永远 suspect"？
5. 资源锁用数据库行锁，在 SQLite 下能不能工作？单 worker 下有没有更简单的做法（进程内锁）？分别什么时候该升级到 Redis？
6. 重定位的触发条件里，"odom 位移 > 5m 但定位未更新"这个判据在机器狗上成立吗（腿式里程计漂移大）？
7. 如果只能在 3 天内做完 2 条，你选哪 2 条？为什么？

要求：犀利、具体、可执行。不要泛泛而谈。
