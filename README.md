# 防爆机器人平台

唯一机器人能力依据：`API接口导航2024_HTTP_20240619142112(1).pdf`（JCROB HTTP/WS，109 页）。

> **接手项目先读 [HANDOFF.md](HANDOFF.md)。** 里面有项目背景、用户约束、已定技术方案、PDF 事实与页码、文件说明、脚本用法、真机联调顺序、已知错误和待确认问题。

## 当前定稿

| 文件 | 用途 |
|---|---|
| [HANDOFF.md](HANDOFF.md) | **交接入口**：上下文、决策、文件地图、联调步骤、风险清单 |
| [docs/平台方案-定稿.md](docs/平台方案-定稿.md) | 平台架构、SDK Adapter、数据模型、API、任务状态机、UI、六周计划、验收 |
| [docs/PDF-SDK能力与平台方案.md](docs/PDF-SDK能力与平台方案.md) | PDF 能力地图、能做什么/不能做什么、真机 12 项确认 |
| [docs/PDF接口原文索引.md](docs/PDF接口原文索引.md) | 178 条 URL 的页码/方法/原文标题，机械提取（脚本生成，勿手改） |
| [docs/JCROB实机兼容性.md](docs/JCROB实机兼容性.md) | URL 编码与兼容别名、字段补正、单位判定记录、待实机确认清单 |
| [docs/真机取数清单.md](docs/真机取数清单.md) | **真机 11/10 直连时按这张表取数**：取什么、从哪个接口、解锁哪些决策、缺什么卡住什么 |
| [真机联调数据采集表.xlsx](真机联调数据采集表.xlsx) | 现场按表填：基础信息、HTTP、WS、任务、能力、问题记录（v1.1） |

## 复现接口清单

```powershell
python scripts/extract_pdf_endpoints.py
```

脚本用 `pdfplumber` 逐页读取 PDF，保留原文空格和拼写，不做 URL 规范化。

方案里引用的 SDK 接口已与索引逐条对过；平台自建的 `/api/v1/...` 接口在文中单独标注为“我设计的，不是 PDF”。

## 本期范围

- 做：状态驾驶舱、地图/点位、任务下发与巡航、告警、历史、审计、基础 RBAC；
- 不做：视频/云台/测温（后续单独接）、BMS 单体电压、AI 识别、MQTT/GB28181、软件急停、多机器人、7×24 录像。

## 历史资料

以下文件保留作参考，但**不再作为机器人能力依据**：

- `防爆机器人平台-实施方案v2.md`（v3.0，含 xlsx 模块矩阵与 UI 照片分析）
- `docs/UI设计基线-实拍参考.md`
- `docs/model_review_20261020-140309.md`
- `docs/open-source-references.md`

## 仓库结构

```text
web/        Vue 3 + TS + Vite 前端（不直连机器人）
server/     FastAPI 后端（Adapter / API / 后台循环 / 迁移）
contracts/  OpenAPI + JCROB fixtures（前后端共用的契约）
deploy/     docker-compose、nginx、两个 Dockerfile
docs/       方案、清单、评审记录
scripts/    probe_jcrob.py 等一次性工具
```

## 快速开始（本地，Mock 机器人）

```powershell
cd server
python -m pip install -e ".[dev]"
copy .env.example .env
python -m uvicorn app.main:app --reload --port 8000
```

- 健康检查：`http://127.0.0.1:8000/health`
- 接口文档：`http://127.0.0.1:8000/docs`
- 默认账号：`admin / admin123`（生产必须改）

前端：

```powershell
cd web
npm install
npm run dev     # http://127.0.0.1:5173，/api 已反代到 8000
```

测试：

```powershell
cd server
python -m pytest tests -q      # 32 项：单位、脱敏、Adapter、登录、CSRF、探针
```

## 依赖原则

前端只有 3 个包（`vue` / `vue-router` / `pinia`），后端只多 8 个（FastAPI、SQLAlchemy、Alembic、PyJWT、httpx、PyMySQL…）。
组件库、图表库现在**不装**：没有页面用到它们，装了就是白背 400 KB 和一堆传递依赖。要用时再引，按需引入。

OpenAPI 契约由代码生成，不手写：

```powershell
python scripts/export_openapi.py   # -> contracts/openapi.json
```

## 当前进度

- ✅ `server/`：配置、日志脱敏、JWT + CSRF、SQLite/MySQL、Alembic 初始迁移、JCROB HTTP Adapter（只读）、Mock Adapter、能力探测、1s 轮询、后台循环 supervisor、`/health` 深探针
- ✅ `web/`：登录、驾驶舱（状态条 / Canvas 地图 / 位姿 / 新鲜度）、地图与点位、任务只读、告警规则页、数据查询、系统设置（能力矩阵 + 运行状态）；**`npm run build` 通过**（vue-tsc strict + vite），dist 134 KB
- ✅ `contracts/`：OpenAPI v0.1 + 12 个 PDF 示例 fixtures
- ✅ `deploy/`：compose（`jc-` 前缀 / 8099 / `/data/jcrob-platform`）+ nginx（日志脱敏）+ 多阶段镜像
- ⬜ 写操作（任务下发/暂停/继续/停止）：**刻意未开放**，等真机联调 + 现场授权签字
- ⬜ WS 监听、告警引擎、历史采样、CSV 导出、审计页（W5）

## 下一步

交付日 **2026-12-01**，部署机 **192.168.8.40**（Ubuntu 22.04 + Docker Compose，nginx 用 8099）。

1. 前端已能构建（`npm install && npm run build` 通过）；下一步补一次浏览器冒烟（Playwright 截图登录→驾驶舱）；
2. W4 前做完驾驶舱与地图的细节，Mock 下 feature-complete；
3. 11/10 真机只读冒烟，跑 `probe_jcrob.py --angle-check`，填采集表；
4. 用真实字段锁定单位、任务语义和地图坐标。
