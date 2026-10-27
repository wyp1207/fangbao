"""设置项审计：schema 里每一项，代码里到底有没有人读。

用法：
  python scripts/audit_settings.py            # 打印 + 写 docs/reviews/settings-audit.md
  python scripts/audit_settings.py --json     # 只输出 JSON
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "server" / "app" / "services" / "settings_schema.py"
SEARCH_DIRS = [ROOT / "server" / "app", ROOT / "web" / "src", ROOT / "scripts", ROOT / "deploy"]
SKIP_DIRS = {"node_modules", "__pycache__", ".git", "dist"}

KEY_RE = re.compile(r'^\s{4}"([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)":\s*\{', re.M)


def iter_files():
    for d in SEARCH_DIRS:
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if not p.is_file() or p.suffix not in {".py", ".ts", ".vue", ".js", ".sh", ".yml", ".yaml", ".conf", ".ini"}:
                continue
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            yield p


def main() -> int:
    text = SCHEMA.read_text(encoding="utf-8")
    keys = KEY_RE.findall(text)
    files = list(iter_files())

    hits: dict[str, list[str]] = {k: [] for k in keys}
    for p in files:
        try:
            body = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for k in keys:
            if k in body:
                rel = p.relative_to(ROOT).as_posix()
                # schema 定义本身不算"有人读"
                if rel.endswith("settings_schema.py"):
                    continue
                hits[k].append(rel)

    rows = []
    for k in keys:
        used = sorted(set(hits[k]))
        rows.append({"key": k, "used": bool(used), "files": used[:5]})

    unused = [r for r in rows if not r["used"]]

    if "--json" in sys.argv:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        print(f"设置项总数：{len(rows)}　有代码读取：{len(rows) - len(unused)}　"
              f"**没人读**：{len(unused)}")
        for r in unused:
            print(f"  ✗ {r['key']}")
        print("\n有读取（前 12 个）：")
        for r in [x for x in rows if x["used"]][:12]:
            print(f"  ✓ {r['key']:<28} {r['files'][0]}")

        out = ROOT / "docs" / "reviews" / "settings-audit.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# 设置项审计：界面上有，代码里有没有人读",
            "",
            f"共 {len(rows)} 项，有代码读取 {len(rows) - len(unused)} 项，**没人读 {len(unused)} 项**。",
            "",
            "> 判定方法：在 server/app、web/src、scripts、deploy 里搜设置键的字面量；",
            "> 只看 settings_schema.py 不算（那是定义本身）。",
            "",
            "| 设置项 | 有代码读 | 生效位置（前 2 处） |",
            "|---|---|---|",
        ]
        for r in rows:
            mark = "✅" if r["used"] else "❌ **没人读**"
            where = "<br>".join(f"`{f}`" for f in r["files"][:2]) or "—"
            lines.append(f"| `{r['key']}` | {mark} | {where} |")
        lines += ["", "## 处理建议", ""]
        if unused:
            lines.append("没人读的项：要么接上（真正生效），要么从设置页删掉——保留假开关比没有更伤信任。")
            for r in unused:
                lines.append(f"- `{r['key']}`")
        else:
            lines.append("没有发现假开关。")
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n已写入 {out.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
