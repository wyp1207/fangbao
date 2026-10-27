"""接口审计：后端有哪些路由，前端到底调没调。

用法：
  python scripts/audit_api.py          # 打印 + 写 docs/reviews/api-audit.md
  python scripts/audit_api.py --json   # 只输出 JSON

判定规则：
- 后端：扫 server/app/api/v1/*.py 的 APIRouter(prefix) + @router.<method>("/path")
- 前端：扫 web/src 里所有字符串/模板里的 /api/v1/... 或 request('/...')、api.xxx() 无法静态推断的，
  所以同时把 api/index.ts 的路径字面量一起扫。
- 路由参数（{id}）按通配匹配。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "server" / "app" / "api" / "v1"
WEB_DIR = ROOT / "web" / "src"

ROUTER_RE = re.compile(r'APIRouter\(\s*prefix\s*=\s*["\']([^"\']*)["\']')
DECOR_RE = re.compile(r'@router\.(get|post|put|patch|delete)\(\s*["\']([^"\']*)["\']')
PATH_LITERAL_RE = re.compile(r'["\'`](/[a-z0-9_\-/{}.]*?)["\'`]')
FULL_PATH_RE = re.compile(r'/api/v1(/[a-z0-9_\-/{}.]*)')


def backend_routes() -> list[dict]:
    routes = []
    for f in sorted(API_DIR.glob("*.py")):
        text = f.read_text(encoding="utf-8", errors="ignore")
        prefixes = ROUTER_RE.findall(text)
        prefix = prefixes[0] if prefixes else ""
        for method, path in DECOR_RE.findall(text):
            full = f"{prefix}{path}" or "/"
            routes.append({"method": method.upper(), "path": full.rstrip("/") or "/",
                           "file": f.relative_to(ROOT).as_posix()})
    return routes


def normalize(path: str) -> str:
    """把 {id}、{video_id} 统一成 {}，用于通配比较。"""
    path = re.sub(r"\{[^}]+\}", "{}", path)
    path = re.sub(r"/+", "/", path)
    return path.rstrip("/") or "/"


def frontend_paths() -> set[str]:
    out: set[str] = set()
    for f in WEB_DIR.rglob("*"):
        if not f.is_file() or f.suffix not in {".ts", ".vue", ".js"}:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")

        # 1) 完整的 /api/v1/...（fetch、<img src>、下载链接）
        for hit in re.findall(r"/api/v1(/[^\s`'\"<>]*)", text):
            out.add(_clean(hit))

        # 2) 反引号/引号里以 / 开头的路径（api/index.ts 的 request('/videos/${id}/mjpeg')）
        for hit in re.findall(r"[`'\"](/[^`'\"\s<>]*)", text):
            if " " in hit or "\\" in hit:
                continue
            out.add(_clean(hit))

        # 3) Vue 模板里直接用拼出来的路径（:src="`/api/v1/...`"）
        for hit in re.findall(r"\$\{?[^}]*\}(/api/v1/[^\s`'\"<>]*)", text):
            out.add(_clean(hit))
    return {p for p in out if p.startswith("/") and len(p) > 1}


def _clean(path: str) -> str:
    """去掉 query/hash，把 ${x} 和 {x} 统一成 {}。"""
    path = path.split("?")[0].split("#")[0]
    path = re.sub(r"/\$\{[^}]*\}", "/{}", path)      # /videos/${id}/x → /videos/{}/x
    if "${" in path:                                  # /notify/logs${qs} → /notify/logs
        path = path.split("${")[0]
    path = re.sub(r"\{[^}]*\}", "{}", path)
    return normalize(path)


def matches(route_path: str, fe: set[str]) -> bool:
    rp = normalize(route_path)
    if rp in fe:
        return True
    # 前缀相同的动态路由：/videos/{}/mjpeg 命中 /videos/1/mjpeg 这种实例
    for f in fe:
        if f.startswith(rp + "/"):
            return True
        if rp.endswith("/{}") and f.startswith(rp[:-2]):
            return True
    return False


def main() -> int:
    routes = backend_routes()
    fe = frontend_paths()
    dead = [r for r in routes if not matches(r["path"], fe)]

    if "--json" in sys.argv:
        print(json.dumps({"routes": len(routes), "dead": dead}, ensure_ascii=False, indent=1))
        return 0

    print(f"后端路由 {len(routes)} 个，前端没调过的 {len(dead)} 个")
    by_file: dict[str, list[str]] = {}
    for r in dead:
        by_file.setdefault(r["file"], []).append(f"{r['method']} {r['path']}")
    for f, items in sorted(by_file.items()):
        print(f"\n{f}（{len(items)}）")
        for i in items:
            print(f"  · {i}")

    out = ROOT / "docs" / "reviews" / "api-audit.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 接口审计：后端有，前端调没调",
        "",
        f"后端路由 {len(routes)} 个，**前端未发现调用 {len(dead)} 个**。",
        "",
        "> 判定：扫 web/src 里的 `/api/v1/...`、`request('/...')`、模板字符串路径；",
        "> 路由参数按通配匹配。命中的路径都算「有人用」（含 `<img src>`、导出链接）。",
        "",
        "## 未调用清单",
        "",
    ]
    if dead:
        lines += ["| 方法 | 路径 | 分类 | 说明 | 所在文件 |", "|---|---|---|---|---|"]
        for r in dead:
            tag, why = CLASSIFY.get(f"{r['method']} {r['path']}", ("待定", "未分类"))
            lines.append(f"| {r['method']} | `{r['path']}` | {tag} | {why} | {r['file']} |")
        buckets: dict[str, list[str]] = {}
        for r in dead:
            tag, _ = CLASSIFY.get(f"{r['method']} {r['path']}", ("待定", ""))
            buckets.setdefault(tag, []).append(f"{r['method']} {r['path']}")
        lines += ["", "## 按分类汇总", ""]
        for tag in ("运维", "外部", "在用", "待接", "待定"):
            if tag in buckets:
                lines.append(f"- **{tag}**（{len(buckets[tag])}）：" + "、".join(f"`{x}`" for x in buckets[tag]))
    else:
        lines.append("没有发现死接口。")
    lines += ["", "## 处理原则", "",
              "- 运维/调试类（health、metrics、probe）：保留，但要在文档里注明「仅运维用」",
              "- 业务类且确实没人用：要么接到界面上，要么删掉——留着只会在验收时被问住",
              ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n已写入 {out.relative_to(ROOT).as_posix()}")
    return 0


# 人工分类：这 19 个里哪些是真没人用、哪些是"运维/外部系统本来就不走前端"
CLASSIFY: dict[str, tuple[str, str]] = {
    # 运维/监控：由探针、Prometheus、k8s/负载均衡调用，不该有前端入口
    "GET /metrics": ("运维", "Prometheus 抓 /metrics，前端不调"),
    "GET /ready": ("运维", "就绪探针"),
    "GET /api/v1/health/deep": ("运维", "健康检查脚本"),
    # 外部系统推送/拉取：给网关、API Key、视觉算法箱用
    "POST /sensors/{sensor_id}/readings/ingest": ("外部", "采集网关/第三方按 Key 推送"),
    "POST /task-runs/ingest": ("外部", "外部系统回报任务状态"),
    "GET /ai/results/{result_id}/image": ("外部", "视觉算法箱返回的图片，前端用 result.image_url"),
    "GET /inspection/photos/{path:path}": ("外部", "照片 URL 由后端拼好，前端只贴 url"),
    "GET /notify/logs": ("在用", "NotifyChannels.vue 的推送日志（静态扫描识别不到模板拼接）"),
    "GET /reports/summary": ("在用", "ReportPrint/Reports 页都调"),
    "GET /reports/export.xlsx": ("在用", "报表页导出链接"),
    # 真·待接
    "GET /robots/runtime": ("待接", "设备运行时总览，建议接到设备页顶部"),
    "GET /robots/{robot_id}/pose": ("待接", "位姿单独接口；首页已用 /status 里的位姿，可不通"),
    "GET /alarms/latest": ("待接", "老接口，前端已改用 /alarms 列表"),
    "POST /devices/reload": ("待接", "改设备台账后重建轮询；后端已在 PATCH 里自动重建，前端无需调"),
    "POST /devices/{device_id}/status-probe": ("待接", "单设备探测，设备页可加「测试连接」按钮"),
    "GET /telemetry/rollup": ("待接", "分钟级聚合，报表长区间可切到它"),
    "GET /videos/{video_id}/live.jpg": ("待接", "首页改用 mjpeg 后这个只剩兜底，保留"),
    "GET /videos/streams/stats": ("待接", "视频转码进程状态，运维页可展示"),
    "DELETE /recordings/{video_id}/all": ("待接", "批量删录像，回放页暂无入口"),
    "PATCH /inspection/plans/{plan_id}": ("待接", "人工巡检计划编辑入口未做"),
    "DELETE /inspection/plans/{plan_id}": ("待接", "人工巡检计划删除入口未做"),
    "POST /maps/library/points/{point_id}/sync": ("待接", "点位同步到机器人，地图页暂无按钮"),
}


if __name__ == "__main__":
    raise SystemExit(main())

