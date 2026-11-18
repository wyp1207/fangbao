"""AI 回调接收端：边缘盒子把原始 payload 推过来，平台只落盘、不映射。

约定（见需求）：
- POST /api/v1/ai/callback/{source_key}，无需登录 / CSRF
- 鉴权：query token 或 header X-Callback-Token，与 env AI_CALLBACK_TOKEN 比对
- 未配置 env → fail-closed 拒绝；错误一律 401
- 落盘 data/ai_callbacks/<YYYYMMDD>/<uuid>.json，含 source_key/received_at/headers(脱敏)/body
- body 上限 2MB，超限 413
- GET /api/v1/ai/callback/ping → {ok: true}（盒子/浏览器自检）
"""

from __future__ import annotations

import json
import re

import pytest

TOKEN = "test-callback-token-not-a-real-secret"
MAX_BODY = 2 * 1024 * 1024
URL = "/api/v1/ai/callback/edge-box-1"


@pytest.fixture(autouse=True)
def _token_env(monkeypatch):
    """默认已配置 token；未配置的用例在用例内 delenv。"""
    monkeypatch.setenv("AI_CALLBACK_TOKEN", TOKEN)


@pytest.fixture
def cb_dir(tmp_path, monkeypatch):
    """把落盘根目录换到临时目录，避免污染 server/data 与互相干扰。"""
    from app.api.v1 import ai_callback

    root = tmp_path / "ai_callbacks"
    monkeypatch.setattr(ai_callback, "ROOT", root)
    return root


def _only_saved(cb_dir, cb_id: str):
    """返回唯一的 <day>/<id>.json 路径，并断言目录名是 YYYYMMDD。"""
    hits = [p for p in cb_dir.glob(f"*/{cb_id}.json")]
    assert len(hits) == 1, f"期望恰好一个落盘文件，实际 {hits}"
    assert re.fullmatch(r"\d{8}", hits[0].parent.name), hits[0].parent.name
    return hits[0]


def test_post_without_token_is_401(client, cb_dir):
    r = client.post(URL, json={"type": "intrusion"})
    assert r.status_code == 401, r.text
    assert not cb_dir.exists()


@pytest.mark.parametrize("where", ["query", "header"])
def test_post_with_wrong_token_is_401(client, cb_dir, where):
    if where == "query":
        r = client.post(f"{URL}?token=wrong-token", json={"type": "intrusion"})
    else:
        r = client.post(URL, json={"type": "intrusion"},
                        headers={"X-Callback-Token": "wrong-token"})
    assert r.status_code == 401, r.text
    assert not cb_dir.exists()


def test_post_with_query_token_saves_raw_payload(client, cb_dir):
    payload = {"type": "person_intrusion", "camera": "CAM-01",
               "ts": "2026-11-17T16:00:00+08:00", "confidence": 0.87}
    raw = json.dumps(payload, ensure_ascii=False).encode()
    r = client.post(f"{URL}?token={TOKEN}", content=raw,
                    headers={"Content-Type": "application/json"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["bytes"] == len(raw)
    assert body["id"]

    saved = json.loads(_only_saved(cb_dir, body["id"]).read_text(encoding="utf-8"))
    assert saved["source_key"] == "edge-box-1"
    assert saved["received_at"]
    assert saved["body"] == payload


def test_post_with_header_token_is_accepted(client, cb_dir):
    r = client.post(URL, json={"type": "smoke"},
                    headers={"X-Callback-Token": TOKEN})
    assert r.status_code == 200, r.text
    assert _only_saved(cb_dir, r.json()["id"]).is_file()


def test_ping_returns_ok_without_token(client):
    r = client.get("/api/v1/ai/callback/ping")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}


def test_oversize_body_is_413(client, cb_dir):
    r = client.post(f"{URL}?token={TOKEN}", content=b"x" * (MAX_BODY + 1),
                    headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 413, r.text
    assert not cb_dir.exists()


def test_unconfigured_env_rejects_everything(client, cb_dir, monkeypatch):
    """fail-closed：没配 AI_CALLBACK_TOKEN 时，带对的 token 也不放行。"""
    monkeypatch.delenv("AI_CALLBACK_TOKEN", raising=False)
    r1 = client.post(URL, json={"a": 1})
    r2 = client.post(f"{URL}?token={TOKEN}", json={"a": 1})
    assert r1.status_code == 401, r1.text
    assert r2.status_code == 401, r2.text
    assert not cb_dir.exists()


def test_saved_headers_are_redacted(client, cb_dir):
    r = client.post(URL, json={"a": 1}, headers={
        "X-Callback-Token": TOKEN,
        "Authorization": "Bearer super-secret-abc",
        "Cookie": "jc_token=super-secret-cookie",
        "X-Box-Id": "BOX-1",
    })
    assert r.status_code == 200, r.text
    path = _only_saved(cb_dir, r.json()["id"])
    text = path.read_text(encoding="utf-8")
    assert TOKEN not in text
    assert "super-secret-abc" not in text
    assert "super-secret-cookie" not in text

    saved = json.loads(text)
    assert saved["headers"]["x-box-id"] == "BOX-1"


def test_callback_ignores_non_callback_body(client, cb_dir):
    """不是真实回调（没有 snowflake/timestamp）就不许写 ai_result。

    真实 18 字段 payload 的入库路径见 `test_ai_callback_ingest.py`。
    """
    from app.db.session import SessionLocal
    from app.models.ai import AiResult

    with SessionLocal() as db:
        before = db.query(AiResult).count()
    r = client.post(f"{URL}?token={TOKEN}", json={"type": "intrusion"})
    assert r.status_code == 200, r.text
    assert r.json()["ingested"] is False
    with SessionLocal() as db:
        assert db.query(AiResult).count() == before
