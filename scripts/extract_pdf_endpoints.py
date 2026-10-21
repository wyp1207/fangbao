#!/usr/bin/env python3
"""Extract every URL entry from the JCROB HTTP protocol PDF.

The output is a Markdown table with page number, method, URL and the heading
immediately above the URL. It is intentionally mechanical: no guessing, no
normalisation. If the PDF prints `/navigation/move to index`, the table keeps
the space.

Usage:
    python scripts/extract_pdf_endpoints.py
    python scripts/extract_pdf_endpoints.py --pdf "path/to/doc.pdf" --out docs/PDF接口原文索引.md
"""

from __future__ import annotations

import argparse
import glob
import re
import sys
from pathlib import Path

import pdfplumber


PAGE_RE = re.compile(r"===== PDF PAGE (\d+) =====")
URL_RE = re.compile(r"^URL[:：]\s*(.+)$")
METHOD_RE = re.compile(r"请求方式[:：]\s*(\S+)")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--pdf", default="", help="PDF path; defaults to the only *.pdf in cwd")
    p.add_argument("--out", default="docs/PDF接口原文索引.md")
    return p.parse_args()


def find_pdf(path: str) -> str:
    if path:
        return path
    found = glob.glob("*.pdf")
    if len(found) != 1:
        raise SystemExit(f"expected exactly one *.pdf in cwd, found {len(found)}; pass --pdf")
    return found[0]


def heading_before(lines: list[str], index: int) -> str:
    for j in range(index - 1, max(index - 8, -1), -1):
        text = lines[j].strip()
        if not text or text.startswith("URL") or text.startswith("====="):
            continue
        if text.startswith("一.JCROB") or text.isdigit():
            continue
        return text
    return ""


def extract(pdf_path: str) -> list[tuple[int, str, str, str]]:
    rows: list[tuple[int, str, str, str]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            lines = (page.extract_text() or "").splitlines()
            for i, line in enumerate(lines):
                m = URL_RE.match(line.strip())
                if not m:
                    continue
                method = ""
                for j in range(i + 1, min(i + 5, len(lines))):
                    mm = METHOD_RE.search(lines[j])
                    if mm:
                        method = mm.group(1)
                        break
                rows.append((page_no, method or "—", m.group(1).strip(), heading_before(lines, i)))
    return rows


def main() -> int:
    args = parse_args()
    pdf_path = find_pdf(args.pdf)
    rows = extract(pdf_path)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# PDF 接口原文索引（机械提取，未改写）",
        "",
        f"> 来源：`{Path(pdf_path).name}`，共 {len(rows)} 条 `URL:` 记录。",
        "> 由 `scripts/extract_pdf_endpoints.py` 用 pdfplumber 逐页提取；页码为 PDF 物理页。",
        "> 说明：PDF 里的空格、大小写、拼写均原样保留，不做 URL 规范化。",
        "",
        "| 页码 | 方法 | URL | 原文标题 |",
        "|---:|---|---|---|",
    ]
    for page_no, method, url, title in rows:
        lines.append(f"| {page_no} | {method} | `{url}` | {title} |")

    spaced = [(p, u) for p, m, u, t in rows if " " in u]
    lines += ["", "## 原文中含空格的 URL（疑似排版/笔误，必须实机确认）", ""]
    if spaced:
        for page_no, url in spaced:
            lines.append(f"- 第 {page_no} 页：`{url}`")
    else:
        lines.append("- 无")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(rows)} URLs -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
