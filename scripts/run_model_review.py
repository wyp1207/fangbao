#!/usr/bin/env python3
"""Run the full-stack review prompt against Doubao Ark and Zhipu GLM.

Keys are read from --key-file (default D:\\Desktop\\api.txt) or env vars
ARK_API_KEY / GLM_API_KEY. Keys are never printed. This script is optional;
the platform does not depend on it.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


ARK_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
GLM_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--key-file", default=r"D:\Desktop\api.txt")
    p.add_argument("--prompt", default="docs/model_review_prompt.md")
    p.add_argument("--out", default="docs")
    p.add_argument("--ark-model", default="doubao-seed-evolving")
    p.add_argument("--glm-model", default="glm-5.2")
    p.add_argument("--max-tokens", type=int, default=4000)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--image", action="append", default=[], help="optional UI image for Doubao; repeatable")
    return p.parse_args()


def load_keys(path: str) -> tuple[str, str]:
    ark = os.environ.get("ARK_API_KEY", "")
    glm = os.environ.get("GLM_API_KEY", "")
    if path and Path(path).exists():
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
        ark = ark or (re.search(r"ark-[A-Za-z0-9\-]+", text).group(0) if re.search(r"ark-[A-Za-z0-9\-]+", text) else "")
        m = re.search(r"glm\s*[:：]\s*([A-Za-z0-9\.]+)", text, re.I)
        glm = glm or (m.group(1) if m else "")
    return ark, glm


def call(url: str, key: str, model: str, prompt: str, max_tokens: int,
         timeout: int, images: list[str] | None = None) -> str:
    content = prompt
    if images:
        content = []
        for image in images:
            b64 = base64.b64encode(Path(image).read_bytes()).decode()
            mime = mimetypes.guess_type(image)[0] or "image/jpeg"
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        content.append({"type": "text", "text": prompt})
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled"},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return data["choices"][0]["message"].get("content", "")


def main() -> int:
    args = parse_args()
    ark, glm = load_keys(args.key_file)
    prompt = Path(args.prompt).read_text(encoding="utf-8")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_file = out_dir / f"model_review_{stamp}.md"

    parts = [f"# 模型评审记录 {stamp}\n"]
    for name, url, key, model in [
        ("豆包 Ark", ARK_URL, ark, args.ark_model),
        ("智谱 GLM", GLM_URL, glm, args.glm_model),
    ]:
        if not key:
            parts.append(f"\n## {name}\n\n未找到密钥，跳过。\n")
            print(f"[skip] {name}: no key")
            continue
        try:
            print(f"[call] {name} model={model}")
            text = call(url, key, model, prompt, args.max_tokens, args.timeout,
                        images=args.image if name.startswith("豆包") else [])
            parts.append(f"\n## {name}（{model}）\n\n{text}\n")
            print(f"[ok] {name}: {len(text)} chars")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:1000]
            parts.append(f"\n## {name}\n\nHTTP {e.code}: {body}\n")
            print(f"[err] {name}: HTTP {e.code}")
        except Exception as e:
            parts.append(f"\n## {name}\n\nERROR: {e}\n")
            print(f"[err] {name}: {e}")

    out_file.write_text("".join(parts), encoding="utf-8")
    print(f"saved: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
