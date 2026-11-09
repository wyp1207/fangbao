"""PATCH /videos/{id}：地址校验、打码密码还原、非法地址必须 400 而不是 500。"""

from __future__ import annotations

import pytest

from app.api.v1.videos import mask_url, split_url, unmask_url
from app.core.errors import BadRequest

ORIG = "rtsp://admin:mt123456@192.168.1.64:554/h264/ch1/main/av_stream"


def _make_video(client) -> dict:
    r = client.post("/api/v1/videos", json={
        "name": "补丁测试-云台", "group_name": "测试", "vendor": "hikvision",
        "url": ORIG, "stream_name": "dog_ptz",
    })
    assert r.status_code == 200, r.text
    return r.json()


def test_split_url_ok():
    assert split_url("rtsp://127.0.0.1:554/test") == ("127.0.0.1", 554)
    assert split_url("rtsp://127.0.0.1/test") == ("127.0.0.1", 554)
    assert split_url("http://cam.local/x") == ("cam.local", 80)


@pytest.mark.parametrize("url,reason", [
    ("rtsp://127.0.0.1:99999/x", "端口"),
    ("rtsp://127.0.0.1:abc/x", "端口"),
    ("not-a-url", "协议"),
    ("rtsp:///nohost", "主机"),
    ("", "不能为空"),
    ("rtsp://host with space/x", "空格"),
    ("rtsp://[::1:554/x", "格式"),
])
def test_split_url_bad_400(url, reason):
    with pytest.raises(BadRequest) as ei:
        split_url(url)
    assert ei.value.status_code == 400
    assert "视频流地址不合法" in ei.value.message
    assert reason in ei.value.message or reason in str(ei.value)


def test_unmask_keeps_password_but_applies_new_host():
    masked = mask_url(ORIG)
    assert "***@" in masked
    got = unmask_url("rtsp://admin:***@10.0.0.9:554/h264/ch1/main/av_stream", ORIG)
    assert "mt123456" in got and "10.0.0.9" in got
    # 原地址没有 userinfo 时明确报错，不能把 *** 悄悄写进库
    with pytest.raises(BadRequest):
        unmask_url("rtsp://admin:***@10.0.0.9/x", "rtsp://10.0.0.9/x")


def test_patch_legal_url_200(auth_client):
    v = _make_video(auth_client)
    r = auth_client.patch(f"/api/v1/videos/{v['id']}", json={"url": "rtsp://127.0.0.1:554/test"})
    assert r.status_code == 200, r.text
    assert r.json()["url"] == "rtsp://127.0.0.1:554/test"
    assert r.json()["stream_name"] == ""      # 换地址清旧流名


def test_patch_masked_url_applies_new_host(auth_client):
    v = _make_video(auth_client)
    masked = v["url"]
    assert "***@" in masked
    new = masked.replace("192.168.1.64", "10.1.2.3")
    r = auth_client.patch(f"/api/v1/videos/{v['id']}", json={"url": new})
    assert r.status_code == 200, r.text
    # 出参还是打码，但主机已经改掉（密码由 unmask_url 还原，单测已覆盖）
    assert r.json()["url"] == "rtsp://admin:***@10.1.2.3:554/h264/ch1/main/av_stream"


@pytest.mark.parametrize("bad", [
    "rtsp://127.0.0.1:99999/x",
    "rtsp://127.0.0.1:abc/x",
    "not-a-url",
    "rtsp:///x",
])
def test_patch_bad_url_400_not_500(auth_client, bad):
    v = _make_video(auth_client)
    r = auth_client.patch(f"/api/v1/videos/{v['id']}", json={"url": bad})
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "BAD_URL"
    assert "视频流地址不合法" in r.json()["message"]


def test_create_with_robot_id_attaches(auth_client):
    """POST 带 robot_id 必须真的挂到设备上；之前 schema 没这个字段，会被静默丢弃。"""
    r = auth_client.post("/api/v1/videos", json={
        "name": "挂设备测试", "url": "rtsp://127.0.0.1:554/test", "robot_id": 1,
    })
    assert r.status_code == 200, r.text
    vid = r.json()["id"]
    rows = auth_client.get("/api/v1/videos?robot_id=1").json()
    rows = rows.get("items", rows) if isinstance(rows, dict) else rows
    assert any(x["id"] == vid for x in rows)

    bad = auth_client.post("/api/v1/videos", json={
        "name": "坏设备", "url": "rtsp://127.0.0.1:554/test", "robot_id": 99999,
    })
    assert bad.status_code == 400 and bad.json()["code"] == "BAD_ROBOT"
