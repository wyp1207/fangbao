# JCROB 实机兼容性记录

> 2026-10-20 · v1.0
>
> 用途：记录“PDF 原文”与“真机实际行为”之间允许存在的差异，以及差异怎么处理。
>
> **不要改 `docs/PDF接口原文索引.md`**：那份由 `scripts/extract_pdf_endpoints.py` 生成，重跑会覆盖。兼容结论一律记在本文件里。

## 1. 总原则

1. URL 按 PDF 原文发，不做规范化、不做大小写修正、不删空格；
2. 需要编码的（空格、中文）在 HTTP 层编码，**编码不是改名**；
3. 只有原文路径实机返回 404/405，才启用兼容别名，并在 Adapter 里显式标记“实机兼容模式”；
4. 任何兼容分支都要能一键关掉，别让兼容代码变成默认路径；
5. 每次兼容性结论都记在本文件第 6 节，带日期、固件版本、请求原文和响应摘要。

## 2. 带空格的 URL（原文即如此）

| PDF 页 | 原文 | 国内实际请求 | 处理 |
|---:|---|---|---|
| 67 | `/navigation/move to index` | `/api/v1/navigation/move%20to%20index` | 先按原文 + `%20` 发；404/405 才用别名 `move_to_index` |
| 65 | `/navigation/upload_map to robot` | `/api/v1/navigation/upload_map%20to%20robot` | 本期不做地图上传，先记着 |

代码里 Adapter 的方法名可以叫 `move_to_index`，但**请求路径必须由常量表给出**，不能靠字符串拼。

## 3. 原文索引里需要补正的地方

| 位置 | 索引/文档写法 | 实际 | 依据 |
|---|---|---|---|
| `/system/self_test` | 方法列“—” | **GET** | PDF p16–17，方法写在翻页后的正文里 |
| `/system/saved_images` | 拍照，方法“—” | **POST**（带可选 `topic` / `filename`） | PDF p34–35 |
| `/system/saved_images/` | GET | 文件列表，带 `/` 结尾 | PDF p34 |
| `/navigation/saved_maps` | `origin` 类型 object | 示例是 **3 元数组** `[x, y, 0.0]` | PDF p55 |
| `/system/is_online` | “在线状态” | 是“机器人能否连上**互联网**” | PDF p34 |
| `/system/info.camera_rgb` 等 | “相机状态” | 是 topic **发布频率 Hz**，0 = 无数据 | PDF p9 |
| `galileo_status.busyStatus` | 布尔 | busy 时“仍接收指令但不立即处理”，队列语义未定义 | PDF p11 |

索引里出现“—”的，只表示提取脚本没抓到“请求方式”那一行，**不代表该方法不存在**。

## 4. 单位判定记录

| 字段 | 候选 | 判定方式 | 判定结果 | 日期 / 固件 |
|---|---|---|---|---|
| `/system/galileo_status.currentAngle` | 度 / 弧度 | `probe_jcrob.py --angle-check`：连续采样 + 圆周误差比 | 待实测 | — |
| `nav_points.theta` | 度 / 弧度 | 样例值域 + 真机点位与 pose 对照 | 按弧度实现，写前必须实测 | — |
| `/navigation/pose.angle` | 度 | PDF p59 明确 | 度 | — |
| `/map/pose.angle` | 度 | PDF p54 明确 | 度 | — |
| `nav_action.theta` | 弧度 | PDF p91 明确 | 弧度 | — |
| `local_move.angle` | 弧度 | PDF p91 明确 | 弧度 | — |

判定脚本：

```powershell
python scripts\probe_jcrob.py --base http://<robot-ip>:3546 --token <token>  `
  --angle-check --angle-check-seconds 40
```

输出 `angle_check.json`：`verdict = deg | rad | inconclusive`，附 `mean_abs_err_if_deg` / `mean_abs_err_if_rad` / `pose_spread_deg`。
机器人静止、两种假设误差差距不足 2 倍、或字段长期是 `-1` 时输出 `inconclusive`，此时页面必须显示“角度单位待确认”，不要猜。

## 5. `path_data` 解析

`/navigation/nav_points`（PDF p72）说明是 8 字段 `x y z theta errorX errorY direction name`，但样例每行只有 7 个（`name` 为空被省略）。

- 读取：`split(maxsplit=7)`，前 7 个固定字段，其余全部归 `name`（名字里带空格不断行）；7 字段时 `name=""`；8 字段且名字为空也接受；
- 写回：`name` 为空按 7 字段输出，**不带尾随空格**；未修改的行原样保留，不整文件重排；
- 写回前必须在一条可丢弃的测试路径上验证一遍，再开放正式点位上传；
- `/navigation/path` 的 `path_data` 是 `x y z` 三字段，**不共用解析器**。

## 6. 兼容性结论登记（现场填）

| 序号 | 日期 | 固件 | 请求（原文） | HTTP | 响应摘要 | 结论 | 处理 |
|---:|---|---|---|---|---|---|---|
| 1 | | | `/api/v1/navigation/move%20to%20index` | | | | |
| 2 | | | `/api/v1/navigation/move_to_index` | | | | |
| 3 | | | `/api/v1/system/config` | | 含哪些敏感字段 | | |
| 4 | | | `/api/v1/task`（读已有嵌套任务） | | | | |
| 5 | | | WS `/galileo/status` ping 格式 | | | | |

## 7. 谁能改什么

| 文件 | 谁能改 |
|---|---|
| `docs/PDF接口原文索引.md` | 只有 `scripts/extract_pdf_endpoints.py`；不要手改 |
| 本文件 | 人和 Agent 都能改，改完写日期 |
| `scripts/probe_jcrob.py` 的 `CONFIG_VIEW_FIELDS` | 改这里等于改 Adapter 的 `ConfigView`，server 端必须同步 |
