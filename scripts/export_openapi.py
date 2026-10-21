#!/usr/bin/env python3
"""从 FastAPI 导出 OpenAPI 到 contracts/openapi.json。

手写 OpenAPI 会立刻和代码漂移，所以契约由代码生成，改完接口跑一次这个脚本即可。
用法：python scripts/export_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from app.main import app  # noqa: E402

OUT = ROOT / "contracts" / "openapi.json"

if __name__ == "__main__":
    OUT.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
