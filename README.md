# 防爆巡检机器人管理平台

单台 **JCROB 轮式防爆巡检机器人**的网页管理平台：实时驾驶舱、地图与点位、视频监控、
告警中心、录像回放、设备台账、系统管理。

前端 Vue 3 + TypeScript + Vite，后端 FastAPI + SQLAlchemy，视频走 go2rtc（MSE），
录像用 ffmpeg 分段落盘。单机 Docker Compose 部署，内网运行。

> 机器人能力依据：`API接口导航2024_HTTP_20240619142112(1).pdf`（JCROB HTTP/WS，109 页）。
> 接手项目先读 [HANDOFF.md](HANDOFF.md)。

---

## 现在的状态（诚实版）

### 真能用（对接真实数据）

| 模块 | 能力 |
|---|---|
| 首页驾驶舱 | 位姿/电量/急停/导航状态、SLAM 地图、机器人轨迹、**内嵌实时视频**、告警统计、消息、点位列表 |
| 实时监控 | 机器人状态、地图（缩放/拖拽/点位）、视频（go2rtc MSE ~0.5s）、充电房 |
| 告警中心 | 平台推导告警（电量/急停/在线）、筛选、分页、**确认→处置→关闭闭环**、一键回看录像、CSV 导出 |
| 告警通知 | 企业微信 / 钉钉 / 通用 Webhook / 邮件外发；按级别触发、按通道静默、投递记录可查 |
| 巡检管理 | 任务列表与动作序列、点位查询（只读） |
| 任务模板 | 平台侧编排：选地图 → 勾点位 → 每点配动作（拍照/录像/停留/云台/热成像）；**不下发**，等授权 |
| 数据查询 | 任务/告警检索与 CSV 导出 |
| 设备管理 | 设备台账 CRUD、连接参数、连通性测试、协议适配器注册表（未实现的标「待接入」并列出缺什么） |
| 多设备监控 | 每台启用的设备独立轮询与缓存，首页切换设备即切数据源；设备增删热重载 |
| 告警通知 | tier 分层：一线立即发，严重告警超时未确认升级给值班长 |
| 地图库 | **导入 PNG 图纸 + 标定比例尺/原点**、点位草稿（点击地图打点，支持分组）、CSV 导入导出、与机器人地图映射 |
| 录像管理 | 启停录制、分段回放（Range 点播）、下载、删除、保留策略（天数/容量/磁盘保护） |
| 系统管理 | 用户 CRUD、角色、重置密码、能力探测、**操作审计日志** |
| 消息中心 | 告警 + 视频/账号/系统事件，落库、未读、筛选 |

### 占位（等设备或数据）

- 热红外视频（无热像仪）
- 环境监测（无可燃气体/温湿度传感器）
- 任务日历（无历史任务库）
- 运行数据曲线（等历史库积累）

### 明确锁着（等真机联调 + 现场授权）

任务下发/暂停/取消、点位同步到机器人、地图下发、云台控制。
点击有说明弹窗，写清「现在什么阶段 / 为什么锁 / 可以先怎么做 / 什么时候开」。

### 没做（不在本期合同）

AI 识别、3D 数字孪生、多机器人调度、GB28181/OPC UA 对接、应急管理局上报。

---

## 仓库结构

```text
web/        Vue 3 + TS + Vite 前端（不直连机器人）
server/     FastAPI 后端（适配器 / API / 后台循环 / 迁移）
contracts/  OpenAPI + JCROB fixtures（前后端共用契约）
deploy/     docker-compose、nginx、两个 Dockerfile
docs/       方案、接口清单、评审记录、截图
scripts/    probe_jcrob.py 等一次性工具
```

后端要点：

```text
server/app/
  adapters/        jcrob(HTTP/Mock) + registry(多设备协议注册表)
  api/v1/          auth devices maps/library alarms messages audit recordings users videos robots
  services/        alarms messages recorder video_stream poller
  models/          robot user video_source alarm message operation_log platform_map
```

---

## 快速开始（本地，Mock 机器人）

```powershell
cd server
python -m pip install -e ".[dev]"
copy .env.example .env
python -m uvicorn app.main:app --reload --port 8000
```

```powershell
cd web
npm install
npm run dev          # http://127.0.0.1:5173
```

默认账号 `admin / admin123`（首次登录后请改密码）。

视频需要 go2rtc：`JC_GO2RTC_BASE=http://<go2rtc>:1984`。

---

## 关键约束（不要绕过）

1. **写操作锁定**：机器人执行类操作要等真机联调通过 + 现场授权签字（方案 §5.7）。
2. **阈值未标定**：环境类告警一律显示「未标定」，不拿占位值冒充。
3. **取消任务 ≠ 安全急停**：急停只能按车体硬件按钮，平台没有急停下发接口。
4. **不造数据**：占位就写「未接入」，宁可空着也不填假值。
5. **录像保留**：默认 30 天 / 800GB，低于 5GB 可用空间自动停录并告警。

---

## 文档

| 文件 | 内容 |
|---|---|
| [HANDOFF.md](HANDOFF.md) | 交接入口：背景、决策、文件地图、联调步骤、风险 |
| [docs/PDF-SDK能力与平台方案.md](docs/PDF-SDK能力与平台方案.md) | PDF 能力地图、能做什么/不能做什么 |
| [docs/PDF接口原文索引.md](docs/PDF接口原文索引.md) | 178 条 URL 的页码/方法/标题 |
| [docs/JCROB实机兼容性.md](docs/JCROB实机兼容性.md) | URL 编码、字段补正、单位判定、待确认清单 |
| [docs/功能模块与接口清单-20261021.xlsx](docs/功能模块与接口清单-20261021.xlsx) | 模块 × 接口对照 |
| [docs/录像保留策略-20261021.xlsx](docs/录像保留策略-20261021.xlsx) | 容量测算与保留规则 |
| [docs/model_review_*.md](docs/) | 豆包 / GLM 的多轮评审记录 |

---

## 版本

`0.1.0` —— 只读阶段。等真机到场（2026-11-10）联调后开放写操作。
