# JCROB fixtures 来源说明

这些 JSON 不是凭空编的，字段与数值取自 PDF 原文示例：

| 文件 | 来源 |
|---|---|
| `system_info.json` | PDF p10 示例（含 `camera_processed` 这个未在字段表里出现的键，故意保留，用来测容错） |
| `system_status.json` | PDF p9，`status` 取值 `Mapping/Navigating/Busy/Free` |
| `galileo_status.json` | PDF p10–11 示例，逐字段照抄，`currentAngle` 保留原值 |
| `self_test.json` | PDF p16–17 字段表 |
| `config.json` | PDF p19–20 字段表；额外塞了 `wifi_ssid`/`wifi_password`，用来验证白名单脱敏 |
| `saved_maps.json` | PDF p55 的 `map_params` + p61 的字段表（`resolution/origin/md5sum/map_type/levels/slam_type`） |
| `nav_points.json` | PDF p72 示例，**每行 7 字段**（`name` 为空被省略） |
| `path.json` | PDF p70：`x y z` 三字段，与 nav_points 不是一种格式 |
| `task.json` / `loop_task.json` | PDF p87 示例结构 |
| `action.json` | PDF p90–96 的动作类型清单 |

> 没做 `point_connections`（跨地图连接点）的 fixture：本期单地图，接口表里也没暴露它。
> 真要用的时候再加，别提前造数据。

替换规则：11/10 真机探针跑完后，把 `probe_out/<ts>/*.json` 里同名文件覆盖到这里即可，
不需要改代码。字段名要与 Adapter 的读取方式一致（见 `server/app/adapters/jcrob/`）。
