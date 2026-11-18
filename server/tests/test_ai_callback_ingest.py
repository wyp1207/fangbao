"""真实回调 → `ai_result` + 图片落盘。

背景：2026-11-18 15:55:34 收到 .170 盒子的真实回调（18 字段），结构与之前的
模拟 payload 完全不同（`result_data` 是列表，框在
`result_data[].result_data.task_result.object_list[]`）。本文件按真实样例
锁定归一化与入库行为：

1. 真实样例的字段映射（external_event_id / 摄像头 / 算法 / 置信度 / 框 / 时间 / 图 URL）
2. 测试包（timestamp 2006-01-02、example.com 图片）必须丢弃，不能污染统计
3. 同 snowflake 重放不新增（`(source_id=1, external_event_id)` 唯一）
4. 图片下载：成功落盘 `data/ai_images/callback/<YYYYMMDD>/<uuid>.jpg`；
   失败/超限不阻塞入库（image_path 留空）
5. 回调接口收到真实 body 后 ai_result +1（下载用 mock，测试不出网）
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.db.init import create_all
from app.db.session import SessionLocal
from app.models.ai import AiResult
from app.services import ai_callback_ingest as ingest_mod
from app.services.ai_callback_ingest import ingest, normalize_callback

TOKEN = "test-callback-token-not-a-real-secret"
URL = "/api/v1/ai/callback/edge-box-1"

# 2026-11-18 15:55:34 的真实回调（按生产落盘 JSON 的 body 逐字段抄下来）
REAL_BODY = {
    "alarm_pic_name": "alarm_2122961895102562304_Picture.jpg",
    "alarm_pic_url": (
        "http://172.16.8.2:8081/dw/fe66d35a779242789f5fec764806a87d/alarm_result/"
        "2026-11-18/15_55/video_files/resultPicture/"
        "alarm_2122961895102562304_Picture.jpg"
    ),
    "algorithm_id": 4,
    "algorithm_name": "行人闯入",
    "algorithm_name_en": "Person-Invasion",
    "analysis_job_id": "fbda6f9adf634cd28bb520f8bc4bcbe3",
    "camera_group": [],
    "camera_id": 13,
    "camera_name": "dog-云台",
    "camera_uuid": "1ad31755a1144c35a5ad45ceb3309605",
    "degree": 3,
    "extra": "",
    "image_height": 1520,
    "image_width": 2688,
    "online_status": 1,
    "result_data": [
        {
            "algorithm_en_name": "Person-Invasion",
            "algorithm_name": "行人闯入",
            "degree": "3",
            "draw_content": [
                {"special_draw": {"rect": {"option": {"color": None}}},
                 "text": "行人闯入", "type": "classId", "value": 1},
            ],
            "other": "",
            "parameter": {
                "option": '[{"name":"rois","type":"roi","vals":[]}]',
            },
            "result_data": {
                "task_id": 4,
                "task_result": {
                    "class_id": 1,
                    "extra_data": "null",
                    "object_list": [
                        {
                            "class_id": 1,
                            "extra_data": "[]",
                            "rect": {"height": 650, "width": 246, "x": 2378, "y": 852},
                            "score": 0.860934,
                            "score_list": [0.860934, 1, 68, 0],
                        },
                    ],
                    "score": 0,
                },
            },
            "task_id": 4,
        },
    ],
    "snowflake_id": 2122961895102562304,
    "timestamp": "2026-11-18 15:55:34",
}

IMAGE_DATA = b"\xff\xd8" + b"\x00" * 4096       # 够长的 JPEG 头
DEFAULT_BASE = "http://192.168.1.170:8081"
PATH_PART = "/dw/fe66d35a779242789f5fec764806a87d/alarm_result/2026-11-18/15_55/video_files/resultPicture/alarm_2122961895102562304_Picture.jpg"


@pytest.fixture(scope="module", autouse=True)
def _schema():
    create_all()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("AI170_IMAGE_BASE", raising=False)


@pytest.fixture
def image_root(tmp_path, monkeypatch):
    root = tmp_path / "ai_images"
    monkeypatch.setattr(ingest_mod, "IMAGE_ROOT", root)
    return root


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def downloads(monkeypatch):
    """把下载替换成内存里的 JPEG，记录每次请求的 URL。"""
    calls: list[str] = []

    def fake_download(url: str, **_: object) -> bytes:
        calls.append(url)
        return IMAGE_DATA

    monkeypatch.setattr(ingest_mod, "download_image", fake_download)
    return calls


def _count_event(db, event_id: str) -> int:
    return (
        db.query(AiResult)
        .filter(AiResult.source_id == ingest_mod.CALLBACK_SOURCE_ID,
                AiResult.external_event_id == event_id)
        .count()
    )


def _cleanup(db, event_id: str) -> None:
    db.query(AiResult).filter(
        AiResult.source_id == ingest_mod.CALLBACK_SOURCE_ID,
        AiResult.external_event_id == event_id,
    ).delete()
    db.commit()


# ---------- 1. 归一化 ----------


def test_normalize_real_callback_maps_every_field():
    item = normalize_callback(REAL_BODY)
    assert item is not None

    assert item["external_event_id"] == "2122961895102562304"
    assert item["algorithm"] == "行人闯入"
    assert item["external_camera_id"] == 13
    assert item["external_camera_name"] == "dog-云台"
    assert item["external_algorithm_id"] == 4
    assert item["confidence"] == pytest.approx(0.860934)
    assert item["ts"] == datetime(2026, 11, 18, 15, 55, 34)
    # 图片主机 172.16.8.2:8081 在本机不可达，必须改写成盒子对外地址
    assert item["source_url"] == DEFAULT_BASE + PATH_PART
    # boxes 是 object_list 原样，前端直接画框
    assert item["boxes"] == REAL_BODY["result_data"][0]["result_data"]["task_result"]["object_list"]


def test_normalize_rewrites_host_from_env(monkeypatch):
    monkeypatch.setenv("AI170_IMAGE_BASE", "http://10.0.0.5:9000")
    item = normalize_callback(REAL_BODY)
    assert item["source_url"] == "http://10.0.0.5:9000" + PATH_PART


def test_confidence_is_max_across_objects():
    objects = [
        {"class_id": 1, "score": 0.42, "rect": {"x": 0, "y": 0, "width": 1, "height": 1}},
        {"class_id": 1, "score": 0.91, "rect": {"x": 1, "y": 2, "width": 3, "height": 4}},
    ]
    task = {
        "task_result": {"object_list": objects},
    }
    body = dict(REAL_BODY, result_data=[{"result_data": task}])
    item = normalize_callback(body)
    assert item["confidence"] == pytest.approx(0.91)
    assert len(item["boxes"]) == 2


# ---------- 2. 测试包 / 非回调 body ----------


@pytest.mark.parametrize("patch", [
    {"timestamp": "2006-01-02 10:00:00"},
    {"alarm_pic_url": "http://example.com/dw/x/alarm_result/a.jpg"},
    # 现场压测常用 example.com 主机 + 保留日期，两个条件命中一个就够
    {"timestamp": "2006-01-02 10:00:00",
     "alarm_pic_url": "http://example.com/x.jpg"},
])
def test_test_package_is_skipped(patch):
    assert normalize_callback(dict(REAL_BODY, **patch)) is None


@pytest.mark.parametrize("body", [
    {"type": "intrusion"},                      # 旧的自定义 payload：没有雪花 id
    {},
    None,
    "not-a-dict",
])
def test_non_callback_body_is_rejected(body):
    assert normalize_callback(body) is None


def test_ingest_skips_test_package_without_touching_db(db, downloads, image_root):
    before = db.query(AiResult).count()
    out = ingest(db, dict(REAL_BODY, timestamp="2006-01-02 10:00:00"))

    assert out["ingested"] is False
    assert out["skipped"] is True
    assert downloads == []                      # 测试包不该去下载图片
    assert db.query(AiResult).count() == before
    assert not image_root.exists()


# ---------- 3. 幂等 ----------


def test_same_snowflake_twice_inserts_once(db, downloads, image_root):
    try:
        first = ingest(db, REAL_BODY)
        second = ingest(db, REAL_BODY)

        assert first["ingested"] is True
        assert first["duplicate"] is False
        assert second["ingested"] is False
        assert second["duplicate"] is True
        assert second["result_id"] == first["result_id"]
        assert _count_event(db, "2122961895102562304") == 1
        assert len(downloads) == 1              # 重复事件不再重复下载
    finally:
        _cleanup(db, "2122961895102562304")


# ---------- 4. 图片落盘 ----------


def test_ingest_writes_result_and_image(db, downloads, image_root):
    event_id = "2122961895102562304"
    try:
        out = ingest(db, REAL_BODY)

        assert out["ingested"] is True
        assert out["image_ok"] is True
        assert out["image_error"] is None

        row = db.get(AiResult, out["result_id"])
        assert row.source_id == ingest_mod.CALLBACK_SOURCE_ID
        assert row.external_event_id == event_id
        assert row.algorithm == "行人闯入"
        assert row.external_camera_id == 13
        assert row.external_camera_name == "dog-云台"
        assert row.external_algorithm_id == 4
        assert row.source_url == DEFAULT_BASE + PATH_PART
        assert row.confidence == pytest.approx(0.860934)
        assert row.ts == datetime(2026, 11, 18, 15, 55, 34)
        assert json.loads(row.boxes_json)[0]["rect"] == {
            "height": 650, "width": 246, "x": 2378, "y": 852}

        # 图片按事件日归档，路径相对 data/，与 /api/v1/ai/results/{id}/image 一致
        assert row.image_path.startswith("ai_images/callback/20261118/")
        saved = image_root / "callback" / "20261118" / Path(row.image_path).name
        assert saved.is_file()
        assert saved.read_bytes() == IMAGE_DATA
        # 原始 payload 留档，便于后面按盒子字段对账
        assert json.loads(row.result_json)["raw"]["snowflake_id"] == 2122961895102562304
    finally:
        _cleanup(db, event_id)


def test_ingest_download_failure_still_writes_row(db, downloads, image_root, monkeypatch):
    def boom(url: str, **_: object) -> bytes:
        raise OSError("connect timeout")

    monkeypatch.setattr(ingest_mod, "download_image", boom)
    event_id = "2122961895102562304"
    try:
        out = ingest(db, REAL_BODY)

        assert out["ingested"] is True
        assert out["image_ok"] is False
        assert "OSError" in (out["image_error"] or "")

        row = db.get(AiResult, out["result_id"])
        assert row is not None
        assert row.image_path is None
        assert image_root.exists() is False     # 失败不落半张图
    finally:
        _cleanup(db, event_id)


def test_oversize_image_is_not_stored(db, image_root, monkeypatch):
    big = b"\xff\xd8" + b"\x00" * (3 * 1024 * 1024)

    monkeypatch.setattr(ingest_mod, "download_image", lambda url, **_: big)
    event_id = "2122961895102562304"
    try:
        out = ingest(db, REAL_BODY)
        assert out["ingested"] is True
        assert out["image_ok"] is False
        assert "3MB" in (out["image_error"] or "") or "size" in (out["image_error"] or "")
        assert db.get(AiResult, out["result_id"]).image_path is None
    finally:
        _cleanup(db, event_id)


def test_non_jpeg_response_is_not_stored(db, image_root, monkeypatch):
    """盒子 404 时常常回一页 HTML；不能把它当 .jpg 存成"证据图"。"""
    monkeypatch.setattr(ingest_mod, "download_image",
                        lambda url, **_: b"<html>404</html>")
    event_id = "2122961895102562304"
    try:
        out = ingest(db, REAL_BODY)
        assert out["ingested"] is True
        assert out["image_ok"] is False
        assert db.get(AiResult, out["result_id"]).image_path is None
    finally:
        _cleanup(db, event_id)


# ---------- 4b. 真实下载函数（本地 socket，不出网） ----------


@pytest.fixture
def image_server():
    """起一个只回固定字节的本地 HTTP 服务；用来验证超时/上限是真的生效。"""
    import http.server
    import threading

    servers: list[http.server.HTTPServer] = []

    def serve(body: bytes, delay: float = 0.0) -> str:
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                import time as _t

                if delay:
                    _t.sleep(delay)
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_port}/alarm.jpg"

    yield serve

    for srv in servers:
        srv.shutdown()
        srv.server_close()


def test_download_image_reads_jpeg(image_server):
    url = image_server(IMAGE_DATA)
    assert ingest_mod.download_image(url) == IMAGE_DATA


def test_download_image_aborts_over_limit(image_server):
    url = image_server(b"\xff\xd8" + b"\x00" * (3 * 1024 * 1024 + 16))
    with pytest.raises(ingest_mod.ImageDownloadError) as exc:
        ingest_mod.download_image(url)
    assert "3MB" in str(exc.value)


def test_download_image_honours_timeout(image_server):
    url = image_server(IMAGE_DATA, delay=1.5)
    with pytest.raises(ingest_mod.ImageDownloadError):
        ingest_mod.download_image(url, timeout=0.3)


# ---------- 5. 回调接口 ----------


@pytest.fixture
def cb_dir(tmp_path, monkeypatch):
    from app.api.v1 import ai_callback

    root = tmp_path / "ai_callbacks"
    monkeypatch.setattr(ai_callback, "ROOT", root)
    monkeypatch.setenv("AI_CALLBACK_TOKEN", TOKEN)
    return root


def test_callback_endpoint_persists_real_body(client, cb_dir, downloads, image_root, db):
    event_id = "2122961895102562304"
    try:
        before = db.query(AiResult).count()
        r = client.post(f"{URL}?token={TOKEN}", json=REAL_BODY)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ingested"] is True
        assert body["result_id"]

        # 原始 JSON 仍然先落盘（排障时以它为准）
        saved = list(cb_dir.glob(f"*/{body['id']}.json"))
        assert len(saved) == 1
        assert json.loads(saved[0].read_text(encoding="utf-8"))["body"] == REAL_BODY

        after = db.query(AiResult).count()
        assert after == before + 1
        assert _count_event(db, event_id) == 1
    finally:
        _cleanup(db, event_id)


def test_callback_endpoint_still_200_when_ingest_blows_up(
        client, cb_dir, image_root, monkeypatch):
    def boom(db, body):  # noqa: ANN001
        raise RuntimeError("db is gone")

    monkeypatch.setattr(ingest_mod, "ingest", boom)
    r = client.post(f"{URL}?token={TOKEN}", json=REAL_BODY)

    # 盒子收到非 2xx 会重推；入库失败不能让原始 payload 也丢
    assert r.status_code == 200, r.text
    assert r.json()["ingested"] is False
    assert len(list(cb_dir.glob("*/" + r.json()["id"] + ".json"))) == 1
