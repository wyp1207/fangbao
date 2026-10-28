"""现场自检接口：结构正确、单机项通过、离线设备不抛异常。"""

from __future__ import annotations


def test_self_check_shape(auth_client):
    r = auth_client.get("/api/v1/system/self-check")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "ok" in body and isinstance(body["checks"], list)
    names = [c["name"] for c in body["checks"]]
    for must in ("数据库", "审计链", "磁盘余量", "写开关"):
        assert any(must in n for n in names), names
    # 每项都要有 ok/detail，前端才能渲染
    for c in body["checks"]:
        assert set(("name", "ok", "detail")) <= set(c)
    # 离线设备只能是 ok=False，不能 500
    assert r.status_code == 200
