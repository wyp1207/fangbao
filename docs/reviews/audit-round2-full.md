# 复审计报告（第二轮）：核对 8 处修复与剩余缺口

- 审计日期：2026-10-28
- 审计对象：`f0205f0` + 当前工作区已暂存改动（`deploy/docker-compose.yml`、`deploy/go2rtc.yaml`、X30 地图空实现、钉钉加签、tier=2 前端入口）
- 方式：读代码 + 干净环境实跑；未修改任何源码，唯一写入物是本文件
- 上一轮报告：`docs/reviews/independent-audit-20261028.md`

> 说明：原定路径 `docs/reviews/independent-audit-round2-20261028.md` 被另一个进程占用（PID 357216，`claude.exe`，该文件正是它的 stdout 重定向），只读审计约束下未终止该进程，故正文写在本文件。

---

## 0. 结论先行

### 0.1 一句话

**还不能说"只剩真机联调"。**

8 条里 5 条真修好（重启恢复、点位锁、报警升级两项、requirements/CI、模板下发），3 条只算部分修复（取消确认、人工接管、巡航暂停）；而 **X30 多点下发的"修复"引入了 P0 回归**：模板里最常见的 `photo/video/wait/thermal` 动作被当成"非导航动作"直接跳过，一条导航都不发；即使动作能导航，`dispatch` 也要等 240s/点，超过 `run_async` 的 60s 上限，真机会先返回 504、车却继续跑。另有 MySQL 自动备份、go2rtc 后端地址两处部署层仍未闭环。

### 0.2 实测记录（不是只看 commit message）

```text
$ python -m pytest -q                                              125 passed, 2 warnings in 14.61s

$ python -m venv /tmp/jc_ci_venv
$ /tmp/jc_ci_venv/.../pip install -r server/requirements.txt       成功（无一缺失包）
$ cd server && python -m pytest -q                                 125 passed, 2 warnings in 14.75s

$ JC_DB_URL=sqlite:////tmp/ci_clean.db python -m alembic upgrade head
  空库 → 0025 全部成功
```

**上一轮"CI 后端 job 必失败"已解除**：`server/requirements.txt` 已存在并入 git（`git ls-files` 可见），干净 venv 能安装、能跑测试、能迁移。CI 现在能到测试步。

### 0.3 新增测试的盲区（重要）

`server/tests/test_audit_fixes.py` 的 5 例只能证明"函数被调用、状态写对"：

- 取消两态把 `_confirm_stopped` 整个 monkeypatch 掉（`test_audit_fixes.py:41-73`），**没有测回读逻辑本身**；
- 暂停只测 `threading.Event` 的 set/clear（`:79-88`），**没测巡航线程真的停/继续**；
- **没有 X30 `dispatch` 测试、没有报警升级测试、没有接管测试**。

所以 125 passed 不代表下面第 1 节里的问题不存在。

---

## 1. 逐条核对（你点名的 8 项）

| # | 检查项 | 判定 | 证据与说明 |
|---|---|---|---|
| 1 | 重启恢复：`mark_stale_runs` 被 main 调用、不再 NameError | **已修复** | `main.py:78-86` 调用；`task_dispatch.py:486-503` 实现；`test_audit_fixes.py:16-28` 通过。残留 `running/dispatched` 会标 failed。小尾巴：`warm_summary` 仍在 `_SL` 定义（`main.py:138`）之前引用它（`:98,101`），靠线程先睡 5 秒掩盖，异常被 `except: pass` 吞掉，只影响报表预热，不影响恢复 |
| 2 | 取消：回读 `get_order`，未停时写 failed | **部分修复** | `task_dispatch.py:344-359` 有回读，`:362-380` 未停写 failed。但 `:352-356` 把任何非 `RUNNING/PAUSED`（含 **UNKNOWN**）当作"已停"；JCROB 任务列表为空就返回 `UNKNOWN`（`http_adapter.py:267-268`），仍会谎报 cancelled。查询异常直接返回 False、不重试（`:357-358`） |
| 3 | 接管：真的调 `adapter.cancel` | **部分修复** | `robots.py:190-208` 调 `registry.get(robot_id).adapter.cancel()`，异步结果经 `run_async`，审计写 `robot_cancel_sent`。但只记"发出去"，**不回读确认**；`adapter is None` 时返回 `null`；命令发出后立刻改库，车是否停未知 |
| 4 | 巡航暂停：`_wait_if_paused` 在循环里生效 | **部分修复** | `cruise.py:70-73` 实现，`:110,131` 在点边界调用。但 **导航中（`_wait_arrival`，`cruise.py:297-342`）和动作执行中不检查暂停**；X30 `pause` 实际是 cancel（`adapter.py:186-188`），`resume` 空操作（`:190-191`），恢复后不会重新下发目标点，`_wait_arrival` 可能等到 240s 超时判 failed |
| 5 | 点位锁：抢不到是否跳过 | **已修复（有保留）** | `cruise.py:159-164` 抢不到直接标 failed 并 `continue`，不再执行动作。保留：锁在**到点之后**才抢，只保护动作阶段，两台车仍可同时驶向同一点；锁本身仍是进程内字典，多实例无效 |
| 6 | X30：是否还只执行第一个动作 | **未修复，且引入回归** | `adapter.py:135-175` 改成串行循环，但 `:149` 把 `photo/video/thermal/wait` 全部 `continue` 掉——而 `ACTIONS` 里模板动作就是这几种（`task_templates.py:27-34`），等于**最常见的模板一条导航都不发**就返回 FINISHED；`:164` 每点最多 240s，但 `_call`→`run_async` 默认 60s（`async_bridge.py:26`，`task_dispatch.py:229` 未传 timeout）；`:157` 的 `nav_goal` 在真机上会因 1003 等任务完成而超时（`goto` 在 `:178-184` 专门捕获了 `TimeoutError`，`dispatch` 没捕），首点即抛异常 → `task_dispatch.py:236-242` 记"结果未知"504 |
| 6b | X30 返回 FINISHED 的副作用 | **新缺陷** | `adapter.py:174` 同步返回 `FINISHED` → `task_dispatch.py:244` 直接把 run 置 done；随后 `_poll_until_done` 因 `run.status != "running"` 立即返回（`task_dispatch.py:282-284`），**步骤状态永远停在 pending**。之前返回 RUNNING 时至少轮询线程会补步骤状态 |
| 7 | 报警升级：排除搁置、无 tier=2 不标 escalated | **已修复** | `notify.py:302-303` 增加搁置过滤；`:317-319` 无 tier=2 通道直接返回、不写 `escalated_at`。前端 tier=2 入口已在暂存改动补上（`NotifyChannels.vue:294-300`）。仍无测试 |
| 8 | CI：`server/requirements.txt` 存在、能到测试步 | **已修复** | 文件已存在并入 git；干净 venv 安装 + `pytest` + `alembic upgrade head` 均实测通过。`ci.yml:21-23` 的路径现在有效 |

---

## 2. 上一轮主要缺陷现状（A1 / A2 / B9 / C13 / D14）

### A1 任务全生命周期 —— **部分修复**

- 模板一键下发 501 **已修复**：`task_templates.py:198-230` 现在创建 `TaskRun`+步骤并调用 `task_dispatch.dispatch`。
- 取消回读 **部分修复**：见上表第 2 条。
- 人工接管 **部分修复**：见上表第 3 条。
- 暂停 **出现语义回退**：`task_dispatch.pause()` 现在把适配器异常一律吞掉（`task_dispatch.py:306-322`）。对**非巡航**的 single-dispatch 任务，JCROB 点"暂停"会返回 200、写 `paused_at`，但车根本没停（`cruise_mod.runner.pause()` 对这类 run 返回 False，没人管）；X30 点"暂停"会 cancel 导航，`resume` 又不重发，任务可能被轮询线程判成 done/failed。上一轮至少会报 `NotSupported`，现在变成**静默成功**。
- 巡航暂停 **部分修复**：见上表第 4 条。
- 仍未做：任务级复盘导出（`reports.py` 不引用 `TaskRun`）、任务记录地图（`TaskRun` 无 `map_id`）、点位同步仍 501（`map_library.py:404`）。
- X30 下发：见上表第 6 条，**比修复前更危险**。

### A2 多机器人 —— **核心未修复，子项修了一个**

- 仍无选车/派单/分区/跨车避让；`robot_id` 为空仍回落 1 号车（`task_runs.py:266`）。
- 点位锁抢不到跳过 **已修复**（`cruise.py:159-164`），但只覆盖动作阶段，不覆盖导航。
- 地图/点位接口仍不按 `robot_id` 路由：`deps.get_adapter()` 固定返回 `app.state.adapter`（`deps.py:82-84`）。
- X30 地图接口 500 风险 **已消除**：暂存改动补了 `get_nav_points/get_current_map/get_map_png` 空实现（`adapter.py:213-224`）。注意 `list_maps` 与 `:115` 重复定义了一次（后定义覆盖前定义，都返回 `[]`，暂无功能影响）。

### B9 报警升级 —— **代码已修复，验证仍缺**

- 搁置不升级、无 tier=2 不标记，均已修（`notify.py:302-303,317-319`）。
- tier=2 前端入口已补（`NotifyChannels.vue:294-300`），API 也接受 `tier`（`notify.py:92`）。
- 仍无升级行为测试；SLA 矩阵仍只管工单，报警升级仍只看 `escalate_after_min`（`sla.py:13` vs `notify.py:274`）。

### C13 指令通道 —— **重启恢复已修，其余未变**

- 重启恢复 **已修复**（见上表第 1 条）。
- 仍无自动重试、无离线发件箱；`_poll_until_done` 仍是未跟踪的 daemon 线程（`task_dispatch.py:257-261`）；停机不 join。
- 幂等/租约/对账保持不变（这部分是加分项）。

### D14 工程与运维 —— **CI 修好，备份仍不工作**

- CI **已修复**，实测能装、能测、能迁移。
- 单 worker / 无 Redis/MQ 不变（刻意设计）。
- **MySQL 自动备份仍未生效**，三个确定性问题：
  1. 运行镜像没装 mysql 客户端：`deploy/server.Dockerfile` 只装 `curl tzdata ffmpeg`，`mysqldump` 不存在 → `FileNotFoundError`；
  2. 库名硬编码 `jc_robot`（`main.py:214`），compose 的库是 `jcrob`（`docker-compose.yml:18`）；
  3. 备份目录 `/app/data/backups` 未挂载（compose 只挂了 `recordings/maps/logs`，`:31-33`），容器重建即丢。
  现在日志会每天 `log.exception("每日备份失败")`，比"静默吞掉"好，但备份数仍是 0。

---

## 3. 当前仍缺清单

### A. 代码/部署能做的（按影响排序，共 10 条）

| # | 缺口 | 影响 |
|---|---|---|
| A1 | X30 模板下发把 `photo/video/wait/thermal` 当非导航动作跳过（`adapter.py:149`） | **P0**：X30 上"一键巡检"不动、还显示完成；验收演示直接翻车 |
| A2 | X30 `dispatch` 不捕获 `nav_goal` 的 TimeoutError，且多点等待超过 `run_async` 60s 上限（`adapter.py:157,164`；`async_bridge.py:26`；`task_dispatch.py:229`） | **P0**：真机首点即 504"结果未知"，车仍在跑；平台状态与实物脱节 |
| A3 | X30 `dispatch` 同步返回 FINISHED，步骤状态永不落库（`adapter.py:174` + `task_dispatch.py:282-284`） | **P1**：任务显示 done，但每个点位都是 pending，复盘无数据 |
| A4 | `pause()` 吞掉 `NotSupported`（`task_dispatch.py:306-322`） | **P1**：非巡航任务点"暂停"返回成功但车没停；比报错更危险 |
| A5 | 巡航暂停只在点边界生效；X30 resume 不重新下发（`cruise.py:110,131,297-342`；`adapter.py:186-191`） | **P1**：客户按"暂停—继续"验收时，车不停/恢复后不走 |
| A6 | 取消把 UNKNOWN 当已停（`task_dispatch.py:352-356`）；且巡航线程收尾会覆盖状态（`cruise.py:189-190` 在 `task_dispatch.cancel` 之后写 `cancelled`） | **P1**：回读修复在巡航路径上被绕过，"已取消"仍可能是假的 |
| A7 | MySQL 备份三处问题（无 mysqldump、库名错、目录未挂载，`main.py:208-215`；`server.Dockerfile`；`docker-compose.yml:31-33`） | **P1**：交付基线"每日自动备份"实际为 0 |
| A8 | go2rtc 容器已加，但 `jc-server` 未设 `JC_GO2RTC_BASE`（compose 只有 `PUBLIC_BASE`；`env.example:17` 还指向 `host.docker.internal`） | **P2**：视频源注册/抓帧仍失败，现场黑屏 |
| A9 | 钉钉 `sign_secret` 前端无输入项、且不在 `SECRET_KEYS`（`notify.py:21`），GET 通道会明文返回；短信通道仍不校验 URL（`notify.py:84-87`） | **P2**：加签功能配不了，密钥会泄露；能建出永远发不出的短信通道（你说的"短信校验"代码里没找到） |
| A10 | 仍无任务级复盘导出、`TaskRun.map_id`、WS/SSE 实时推送；企微/钉钉/邮件无 E2E；遥测/HTTP ingest/WS/MQTT 无测试 | **P3**：范围与质量项，验收可能被追问，但不阻塞演示 |

> 注：A10 是上一轮 E17 的第 5/7/8 条，本轮没有动作。发布前建议至少补 A1-A4。

### B. 必须真机/现场/HIL 才能做的

1. **协议连通与时序**：X30 1003/1007 的实际响应时机、JCROB HTTP 固件差异、角度单位（度/弧度）实测。
2. **急停/暂停/恢复的物理验证**：车是否真的停、停多快、有无滑行；取消后回读的状态是否可信。
3. **到点精度与定位**：到点半径、定位漂移、`set_initial_pose` 后的重定位效果。
4. **X30 多点串行导航的真实可行性**：240s/点是否够、多点之间是否需要重新建图/重定位。
5. **弱网与断网续跑**：丢包、超时、重连后的订单状态；平台重启与车端继续执行的交叉场景。
6. **≥8h/7×24 长稳**：现在只有 3 分钟浸泡，内存/线程/连接泄漏未验证。
7. **真实外发通道**：客户自己的企微/钉钉（含加签）/短信网关/邮件账号各发一条。
8. **现场数据接入**：真实气表 Modbus RTU-over-SSH、MQTT 网关、机器人 WS 推送。
9. **视频链路**：现场摄像头 RTSP、go2rtc 取流、nginx 反代 `/go2rtc/`。
10. **HIL/兼容性矩阵**：固件版本、响应码、结论表填写（`docs/JCROB实机兼容性.md` 仍为空模板）。

---

## 4. 直接回答

**不能。**

一句话：**X30 的模板下发现在是"不发导航/必超时/步骤不落库"的 P0 回归，加上暂停静默成功和 MySQL 备份仍为 0，这些是代码和部署能修的，真机到场只会把它们暴露得更彻底，不会自动消失。**

---

## 附录：本次实际执行的命令

```text
$ cd server && python -m pytest -q
125 passed, 2 warnings in 14.61s

$ python -m venv /tmp/jc_ci_venv
$ /tmp/jc_ci_venv/Scripts/python.exe -m pip install -q -r server/requirements.txt
（退出码 0）

$ cd server && /tmp/jc_ci_venv/Scripts/python.exe -m pytest -q
125 passed, 2 warnings in 14.75s

$ JC_DB_URL=sqlite:////tmp/ci_clean.db /tmp/jc_ci_venv/Scripts/python.exe -m alembic upgrade head
（空库升级到 0025 成功）
```

两条 warning 与上一轮相同：TestClient 的 `httpx` 弃用提示；`test_migrations.py` 在中文 Windows 上读子进程输出 `UnicodeDecodeError`（测试仍 passed）。

## 审计边界

- 只核实代码与仓库内证据；未修改任何源码、配置、迁移或测试。
- 本轮按"当前工作区"审计（HEAD `f0205f0` + 已暂存改动）。若后续又有提交，个别行号可能漂移。
- 未连接真机，不对"协议是否通、坐标是否准"下结论；只对"代码是否具备该能力、闭环是否成立"下结论。
