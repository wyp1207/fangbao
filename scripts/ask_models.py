"""调用豆包（Responses API，兼容 chat/completions）与 GLM，产出评审文件。

密钥从 D:\\Desktop\\api.txt 或环境变量读，绝不打印。
用法：
  python scripts/ask_models.py --prompt docs/xxx.md --out docs/reviews --only doubao
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

ARK_RESPONSES = "https://ark.cn-beijing.volces.com/api/v3/responses"
ARK_CHAT = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
GLM_CHAT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"


def load_keys(path: str) -> tuple[str, str]:
    ark = os.environ.get("ARK_API_KEY", "")
    glm = os.environ.get("GLM_API_KEY", "")
    p = Path(path)
    if p.exists():
        text = p.read_text(encoding="utf-8", errors="ignore")
        ark = ark or (re.search(r"ark-[A-Za-z0-9\-]+", text).group(0)
                      if re.search(r"ark-[A-Za-z0-9\-]+", text) else "")
        m = re.search(r"glm\s*[:：]\s*([A-Za-z0-9\.\-]+)", text, re.I)
        glm = glm or (m.group(1) if m else "")
        if not glm:
            # api.txt 里 glm 行通常直接是 key
            for line in text.splitlines():
                if "glm" in line.lower():
                    tail = re.split(r"[:：]", line)[-1].strip()
                    if len(tail) > 20:
                        glm = tail
    return ark, glm


def _img_part(path: str) -> dict:
    import base64
    import mimetypes

    mime = mimetypes.guess_type(path)[0] or "image/png"
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    return {"type": "input_image", "image_url": "data:%s;base64,%s" % (mime, b64)}


def call_responses(key: str, model: str, prompt: str, timeout: int = 300,
                   images: list[str] | None = None) -> tuple[bool, str]:
    content = [{"type": "input_text", "text": prompt}]
    for img in images or []:
        content.append(_img_part(img))
    body = {"model": model, "input": [{"role": "user", "content": content}]}
    try:
        r = requests.post(ARK_RESPONSES, headers={"Authorization": "Bearer %s" % key},
                          json=body, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return False, "ERR %s" % exc
    if r.status_code != 200:
        return False, "HTTP %s: %s" % (r.status_code, r.text[:300])
    data = r.json()
    text = data.get("output_text") or ""
    if not text:
        chunks = []
        for item in data.get("output") or []:
            for c in item.get("content") or []:
                if c.get("type") in ("output_text", "text"):
                    chunks.append(c.get("text") or "")
        text = "\n".join(chunks)
    return bool(text), text or json.dumps(data)[:300]


def call_chat(url: str, key: str, model: str, prompt: str, timeout: int = 300) -> tuple[bool, str]:
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8000}
    try:
        r = requests.post(url, headers={"Authorization": "Bearer %s" % key}, json=body, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return False, "ERR %s" % exc
    if r.status_code != 200:
        return False, "HTTP %s: %s" % (r.status_code, r.text[:300])
    data = r.json()
    try:
        return True, data["choices"][0]["message"]["content"]
    except Exception:  # noqa: BLE001
        return False, str(data)[:300]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", default="docs/reviews")
    ap.add_argument("--key-file", default=r"D:\Desktop\api.txt")
    ap.add_argument("--ark-model", default="doubao-seed-evolving")
    ap.add_argument("--glm-model", default="glm-5.2")
    ap.add_argument("--only", default="both", choices=["both", "doubao", "glm"])
    ap.add_argument("--image", action="append", default=[], help="给豆包附截图（可多次）")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    ark, glm = load_keys(args.key_file)
    prompt = Path(args.prompt).read_text(encoding="utf-8")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = out / ("model_review_%s.md" % stamp)
    parts = ["# 模型评审记录 %s\n" % stamp]

    if args.only in ("both", "doubao"):
        ok, text = call_responses(ark, args.ark_model, prompt, timeout=args.timeout, images=args.image)
        if not ok:
            print("[warn] Responses API 失败，回退 chat/completions:", text[:120])
            ok, text = call_chat(ARK_CHAT, ark, args.ark_model, prompt, timeout=args.timeout)
        print("[%s] 豆包 %s" % ("ok" if ok else "err", len(text)))
        parts.append("## 豆包 %s\n\n%s\n" % (args.ark_model, text))

    if args.only in ("both", "glm"):
        ok, text = call_chat(GLM_CHAT, glm, args.glm_model, prompt, timeout=args.timeout)
        print("[%s] GLM %s" % ("ok" if ok else "err", len(text)))
        parts.append("## 智谱 %s\n\n%s\n" % (args.glm_model, text))

    target.write_text("\n".join(parts), encoding="utf-8")
    print("saved:", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
