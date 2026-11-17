"""Phase 4：CRIP 盒子适配器与 ai_sync 轮询。

覆盖四类行为：
1. `normalize_log` 字段映射（id/相机/算法/时间/图片 URL/原始 JSON/空 result）
2. 全分页：按 total 取完所有页，跨页重复 id 只算一次，游标按窗口推进
3. 幂等：同一 id 重复写入只留一条
4. 适配器细节：内存 token、401/403 重试一次、图片 Bearer、凭据缺失报错
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import httpx
import pytest

from app.adapters.ai.crip import (
    CripAuthError,
    CripClient,
    CripConfigError,
)
from app.db.init import create_all
from app.db.session import SessionLocal
from app.models.ai import AiResult, AiSource
from app.services.ai_sync import backfill, backoff_delay, normalize_log, poll_once

BASE = "http://192.168.1.170:8081"

SAMPLE = {
    "id": "2687",
    "alert_type": "火焰识别",
    "algorithms": ["火焰识别"],
    "camera_id": 2,
    "camera_name": "实验室二楼门口",
    "degree": 3,
    "created_at": "2026-11-17 12:34:56",
    "url": "/dw/2026/11/17/fire.jpg",
    "origin": "/dw/2026/11/17/fire.jpg",
    "image_width": 1920,
    "image_height": 1080,
    "result": [],
    "extra": [],
    "associate_result": [],
    "analysis_job_name": "lab-job",
    "stream_url": "rtsp://127.0.0.1:554/live",
}


@pytest.fixture(scope="module", autouse=True)
def _schema():
    """单测直接用 DB，不经过 FastAPI 启动流程，先保证表存在。"""
    create_all()


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def source(db):
    src = AiSource(
        name=f"test-crip-{datetime.now().strftime('%H%M%S%f')}",
        base_url=BASE,
        vendor="crip",
        auth_type="openapi",
        auth_ref="AI170",
        poll_interval_s=5,
        enabled=True,
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    yield src
    db.query(AiResult).filter(AiResult.source_id == src.id).delete()
    db.query(AiSource).filter(AiSource.id == src.id).delete()
    db.commit()


def _crip(handler) -> tuple[CripClient, httpx.Client]:
    """真适配器 + MockTransport：测的是请求形状和解析，不是 mock。"""
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return CripClient(BASE, "app-id", "app-secret", http_client=http), http


# ---------- 1. 归一化 ----------


def test_normalize_log_maps_fields():
    item = normalize_log(SAMPLE, BASE)

    assert item["external_event_id"] == "2687"
    assert item["camera_external_id"] == 2
    assert item["algorithm"] == "火焰识别"
    assert item["ts"] == datetime(2026, 11, 17, 12, 34, 56)
    assert item["image_url"] == BASE + "/dw/2026/11/17/fire.jpg"
    assert item["raw_json"] == SAMPLE
    assert item["boxes"] == []
    assert item["confidence"] == 0.0


def test_normalize_log_empty_result_has_no_boxes():
    item = normalize_log({**SAMPLE, "result": []}, BASE)

    assert item["boxes"] == []


def test_normalize_log_boxes_and_confidence():
    record = {
        **SAMPLE,
        "result": [
            {"class_id": 1, "score": 0.91,
             "rect": {"x": 120, "y": 80, "width": 64, "height": 128}},
        ],
    }

    item = normalize_log(record, BASE)

    assert item["boxes"] == [
        {"class_id": 1, "score": 0.91, "x": 120, "y": 80, "w": 64, "h": 128},
    ]
    assert item["confidence"] == pytest.approx(0.91)


# ---------- 2. 分页：取完 total、去重、游标推进 ----------


def _page_handler(ids: list[str], *, total: int, bodies: list[dict], auth: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/openapi/mc/v1/authenticate":
            auth["calls"] += 1
            return httpx.Response(200, json={"accessToken": "userToken=test"})
        if request.url.path == "/openapi/cb/v1/log/search":
            body = json.loads(request.content)
            bodies.append(body)
            page = int(body["current"])
            size = int(body["page_size"])
            chunk = ids[(page - 1) * size: page * size]
            rows = [{**SAMPLE, "id": i} for i in chunk]
            return httpx.Response(200, json={
                "data": rows, "current": page, "page_size": size, "total": total,
            })
        return httpx.Response(404)

    return handler


def test_poll_pages_until_total_dedupes_and_advances_cursor(db, source):
    bodies: list[dict] = []
    auth = {"calls": 0}
    # 5 个唯一 id，但第 2 页夹一个重复 id：跨页去重
    ids = ["101", "102", "103", "104", "105", "103"]
    crip, http = _crip(_page_handler(ids, total=5, bodies=bodies, auth=auth))
    cursor = datetime(2026, 11, 17, 12, 0, 0)
    now = datetime(2026, 11, 17, 12, 1, 0)
    source.last_poll_at = cursor
    db.commit()

    try:
        result = poll_once(db, source.id, client=crip, now=now, page_size=3)
    finally:
        http.close()

    assert result["ok"] is True
    assert result["total"] == 5
    assert result["fetched"] == 6
    assert result["inserted"] == 5
    assert result["duplicates"] == 1
    assert result["pages"] == 2

    # 重叠窗 30s：从 cursor-30s 拉到 now
    assert [b["current"] for b in bodies] == [1, 2]
    assert bodies[0]["start_date"] == "2026-11-17 11:59:30"
    assert bodies[0]["end_date"] == "2026-11-17 12:01:00"
    assert bodies[0]["log_type"] == "video"

    # 游标推进到本轮窗口末尾
    db.refresh(source)
    assert source.last_poll_at == now
    assert source.last_error is None

    rows = db.query(AiResult).filter(AiResult.source_id == source.id).all()
    assert len(rows) == 5
    assert {r.external_event_id for r in rows} == {"101", "102", "103", "104", "105"}
    # 图片先不下载，URL 与原始 JSON 一起留在 result_json
    stored = json.loads(rows[0].result_json)
    assert stored["image_url"].startswith(BASE + "/dw/")
    assert stored["raw"]["id"] == rows[0].external_event_id


def test_poll_twice_is_idempotent(db, source):
    bodies: list[dict] = []
    auth = {"calls": 0}
    ids = ["201", "202", "203", "204", "205"]
    crip, http = _crip(_page_handler(ids, total=5, bodies=bodies, auth=auth))
    source.last_poll_at = datetime(2026, 11, 17, 12, 0, 0)
    db.commit()

    try:
        first = poll_once(db, source.id, client=crip,
                          now=datetime(2026, 11, 17, 12, 1, 0), page_size=3)
        second = poll_once(db, source.id, client=crip,
                           now=datetime(2026, 11, 17, 12, 1, 5), page_size=3)
    finally:
        http.close()

    assert first["inserted"] == 5
    assert second["inserted"] == 0
    assert second["duplicates"] == 5
    assert db.query(AiResult).filter(AiResult.source_id == source.id).count() == 5
    # token 在内存复用，两次轮询只认证一次
    assert auth["calls"] == 1


def test_poll_redacts_stream_url_credentials_in_result_json(db, source):
    """原始记录要留档，但 RTSP 口令不能跟着进库。"""
    record = {**SAMPLE, "id": "501",
              "stream_url": "rtsp://admin:topsecret@192.168.1.14:554/live"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/openapi/mc/v1/authenticate":
            return httpx.Response(200, json={"accessToken": "userToken=test"})
        return httpx.Response(200, json={
            "data": [record], "current": 1, "page_size": 100, "total": 1,
        })

    crip, http = _crip(handler)
    try:
        result = poll_once(db, source.id, client=crip,
                           now=datetime(2026, 11, 17, 12, 1, 0))
    finally:
        http.close()

    assert result["inserted"] == 1
    row = db.query(AiResult).filter(AiResult.source_id == source.id).one()
    stored = json.loads(row.result_json)
    assert "topsecret" not in json.dumps(stored, ensure_ascii=False)
    assert stored["raw"]["stream_url"] == "rtsp://192.168.1.14:554/live"
    assert stored["raw"]["id"] == "501"


def test_backfill_writes_range_without_moving_poll_cursor(db, source):
    bodies: list[dict] = []
    auth = {"calls": 0}
    crip, http = _crip(_page_handler(["301", "302"], total=2, bodies=bodies, auth=auth))
    start = datetime(2026, 11, 16, 0, 0, 0)
    end = datetime(2026, 11, 16, 1, 0, 0)

    try:
        result = backfill(db, source.id, start, end, client=crip, page_size=100)
    finally:
        http.close()

    assert result["inserted"] == 2
    assert bodies[0]["start_date"] == "2026-11-16 00:00:00"
    assert bodies[0]["end_date"] == "2026-11-16 01:00:00"
    db.refresh(source)
    assert source.last_poll_at is None
    assert db.query(AiResult).filter(AiResult.source_id == source.id).count() == 2


def test_poll_failure_rolls_back_window_and_records_error(db, source):
    """第 2 页失败时，第 1 页已写入的行必须回滚，游标不前进。"""
    calls = {"search": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/openapi/mc/v1/authenticate":
            return httpx.Response(200, json={"accessToken": "userToken=test"})
        calls["search"] += 1
        if calls["search"] == 1:
            rows = [{**SAMPLE, "id": i} for i in ("401", "402", "403")]
            return httpx.Response(200, json={
                "data": rows, "current": 1, "page_size": 3, "total": 5,
            })
        return httpx.Response(500, json={"data": {"errorCode": 500}})

    crip, http = _crip(handler)
    cursor = datetime(2026, 11, 17, 12, 0, 0)
    source.last_poll_at = cursor
    db.commit()
    try:
        result = poll_once(db, source.id, client=crip,
                           now=datetime(2026, 11, 17, 12, 1, 0), page_size=3)
    finally:
        http.close()

    assert result["ok"] is False
    assert "CripHttpError" in result["error"]
    assert db.query(AiResult).filter(AiResult.source_id == source.id).count() == 0
    db.refresh(source)
    assert source.last_poll_at == cursor
    assert "CripHttpError" in (source.last_error or "")



def test_backoff_delay_grows_and_caps():
    assert backoff_delay(0, 5) == 5
    assert backoff_delay(1, 5) == 5
    assert backoff_delay(2, 5) == 10
    assert backoff_delay(3, 5) == 20
    assert backoff_delay(10, 5) == 60


# ---------- 3. 适配器：认证/重试/列表/图片 ----------


def test_missing_credentials_raises(monkeypatch):
    monkeypatch.delenv("AI170_APP_ID", raising=False)
    monkeypatch.delenv("AI170_APP_SECRET", raising=False)

    with pytest.raises(CripConfigError):
        CripClient.from_env(BASE)


@pytest.mark.parametrize("status", [401, 403])
def test_retries_once_on_auth_error(status):
    calls = {"auth": 0, "search": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/openapi/mc/v1/authenticate":
            calls["auth"] += 1
            return httpx.Response(200, json={"accessToken": "userToken=test"})
        calls["search"] += 1
        if calls["search"] == 1:
            return httpx.Response(status, json={"data": {"errorCode": 210020027}})
        return httpx.Response(200, json={
            "data": [{**SAMPLE, "id": "1"}], "current": 1, "page_size": 100, "total": 1,
        })

    crip, http = _crip(handler)
    try:
        page = crip.search_logs(datetime(2026, 11, 17), datetime(2026, 11, 18))
    finally:
        http.close()

    assert page.total == 1
    assert page.records[0]["id"] == "1"
    assert calls == {"auth": 2, "search": 2}


def test_list_cameras_and_algorithms_normalize_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/openapi/mc/v1/authenticate":
            return httpx.Response(200, json={"accessToken": "userToken=test"})
        if request.url.path == "/openapi/usm/v1/camera/list":
            return httpx.Response(200, json={
                "data": [{"id": 7, "camera_id": "48e020d4", "name": "实验室",
                          "online_status": 1, "stream_url": "rtsp://cam"}],
                "current": 1, "page_size": 50, "total": 1,
            })
        if request.url.path == "/openapi/am/v1/algorithm/config/list":
            return httpx.Response(200, json={
                "data": [{"algorithm_id": 21, "name": "火焰识别", "name_en": "Fire",
                          "degree": 3}],
                "current": 1, "page_size": 100, "total": 1,
            })
        return httpx.Response(404)

    crip, http = _crip(handler)
    try:
        cameras = crip.list_cameras()
        algorithms = crip.list_algorithms()
    finally:
        http.close()

    assert cameras == [{"id": 7, "camera_id": "48e020d4", "name": "实验室",
                        "online_status": 1, "stream_url": "rtsp://cam"}]
    assert algorithms == [{"algorithm_id": 21, "name": "火焰识别",
                           "name_en": "Fire", "degree": 3}]


def test_download_image_sends_bearer_and_returns_bytes():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/openapi/mc/v1/authenticate":
            return httpx.Response(200, json={"accessToken": "userToken=test"})
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, content=b"\xff\xd8jpeg",
                              headers={"content-type": "image/jpeg"})

    crip, http = _crip(handler)
    try:
        image = crip.download_image("/dw/2026/11/17/fire.jpg")
    finally:
        http.close()

    assert image.status_code == 200
    assert image.content == b"\xff\xd8jpeg"
    assert seen["auth"] == "Bearer userToken=test"


def test_download_image_retries_once_on_403():
    calls = {"image": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/openapi/mc/v1/authenticate":
            return httpx.Response(200, json={"accessToken": "userToken=test"})
        calls["image"] += 1
        return httpx.Response(403, json={"data": {"errorCode": 210020027}})

    crip, http = _crip(handler)
    try:
        with pytest.raises(CripAuthError) as exc:
            crip.download_image("/dw/2026/11/17/fire.jpg")
    finally:
        http.close()

    assert exc.value.status_code == 403
    assert calls["image"] == 2
