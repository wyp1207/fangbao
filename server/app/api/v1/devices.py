"""多设备管理：设备台账 + 连接参数 + 连通性测试。

要点（对着"加一台云深处 X30 需要什么"回答）：
- 不是只填 ID：至少要有 **类型 / 协议 / 主机 / 端口 / 账号 / 密码**；
- 协议决定用哪个适配器，未实现的一律标"待接入"并说明缺什么；
- 密码落库前用 `seal()` 封存，接口永远不返回；
- "测试连接"只做 TCP 可达 + （JCROB）HTTP /api/v1/status 探测，不写任何东西。
"""

from __future__ import annotations

import socket
from typing import Any

from fastapi import APIRouter, Depends, Query
from datetime import date

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.registry import ADAPTERS, DEVICE_TYPES, AdapterNotSupported, build_for
from app.api.deps import get_cache, get_current_user, require_csrf, require_roles
from app.core.config import get_settings
from app.core.errors import BadRequest, NotFound
from app.core.security import seal, unseal
from app.db.session import get_db
from app.models.robot import Robot
from app.models.user import User
from app.services.messages import audit, store as msg_store

router = APIRouter(prefix="/devices", tags=["devices"])


class DeviceOut(BaseModel):
    id: int
    name: str
    device_type: str
    adapter: str
    adapter_label: str
    supported: bool
    station: str
    ip: str
    port: int
    ws_port: int
    username: str | None = None
    mode: str
    is_active: bool
    version: str | None = None
    slam_type: str | None = None
    last_seen: str | None = None
    note: str | None = None
    needs: list[str] = []
    # 防爆台账
    asset_no: str | None = None
    ex_marking: str | None = None
    ex_cert_no: str | None = None
    ex_cert_expiry: date | None = None
    ex_zone: str | None = None
    owner: str | None = None
    maint_due: date | None = None


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    device_type: str = "jcrob_wheel"
    adapter: str = "jcrob_http"
    station: str = "默认场站"
    ip: str = Field(min_length=1, max_length=64)
    port: int = 3546
    ws_port: int = 3547
    username: str | None = None
    password: str | None = None
    mode: str = "http"
    note: str | None = None

    # 防爆资产台账
    asset_no: str | None = None
    ex_marking: str | None = None
    ex_cert_no: str | None = None
    ex_cert_expiry: date | None = None
    ex_zone: str | None = None
    owner: str | None = None
    maint_due: date | None = None


class DevicePatch(BaseModel):
    name: str | None = None
    device_type: str | None = None
    adapter: str | None = None
    station: str | None = None
    ip: str | None = None
    port: int | None = None
    ws_port: int | None = None
    username: str | None = None
    password: str | None = None
    mode: str | None = None
    note: str | None = None
    is_active: bool | None = None

    # 防爆资产台账
    asset_no: str | None = None
    ex_marking: str | None = None
    ex_cert_no: str | None = None
    ex_cert_expiry: date | None = None
    ex_zone: str | None = None
    owner: str | None = None
    maint_due: date | None = None



async def _reload_polling(db: Session) -> None:
    """设备台账变了就重建轮询任务（新增设备不用重启服务）。"""
    from app.services.robot_runtime import registry as robot_registry

    await robot_registry.stop()
    await robot_registry.start(db.query(Robot).filter(Robot.is_active.is_(True)).all())


def _out(r: Robot) -> DeviceOut:
    meta = ADAPTERS.get(r.adapter or "", {})
    return DeviceOut(
        id=r.id, name=r.name, device_type=r.device_type, adapter=r.adapter,
        adapter_label=meta.get("label", r.adapter), supported=bool(meta.get("supported")),
        station=r.station, ip=r.ip, port=r.port, ws_port=r.ws_port,
        username=r.username, mode=r.mode, is_active=r.is_active,
        version=r.version, slam_type=r.slam_type,
        last_seen=r.last_seen.isoformat(timespec="seconds") if r.last_seen else None,
        note=r.note, needs=meta.get("needs", []),
        asset_no=r.asset_no, ex_marking=r.ex_marking, ex_cert_no=r.ex_cert_no,
        ex_cert_expiry=r.ex_cert_expiry, ex_zone=r.ex_zone,
        owner=r.owner, maint_due=r.maint_due,
    )


@router.post("/reload", dependencies=[Depends(require_csrf)])
async def reload_polling(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> dict:
    """设备台账变了，重建轮询任务（新增设备不用重启服务）。"""
    from app.services.robot_runtime import registry as robot_registry

    await robot_registry.stop()
    await robot_registry.start(db.query(Robot).filter(Robot.is_active.is_(True)).all())
    return {"ok": True, "robots": [rt.status() for rt in robot_registry.runtimes.values()]}


@router.get("/meta")
def device_meta(_: User = Depends(get_current_user)) -> dict:
    """前端下拉用：设备类型、协议清单、每个协议缺什么。"""
    return {"device_types": DEVICE_TYPES, "adapters": ADAPTERS}


@router.get("")
def list_devices(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[DeviceOut]:
    return [_out(r) for r in db.query(Robot).order_by(Robot.id).all()]


@router.post("", dependencies=[Depends(require_csrf)])
async def create_device(
    body: DeviceIn,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin")),
) -> DeviceOut:
    if body.adapter not in ADAPTERS:
        raise BadRequest(f"未知协议 {body.adapter}", code="BAD_ADAPTER")
    if db.query(Robot).filter(Robot.name == body.name).first():
        raise BadRequest("设备名已存在", code="NAME_TAKEN")

    settings = get_settings()
    r = Robot(
        name=body.name, device_type=body.device_type, adapter=body.adapter,
        station=body.station, ip=body.ip, port=body.port, ws_port=body.ws_port,
        username=body.username, mode=body.mode, note=body.note,
        password_cipher=seal(body.password or "", secret=settings.secret_key),
        # 防爆台账
        asset_no=body.asset_no, ex_marking=body.ex_marking, ex_cert_no=body.ex_cert_no,
        ex_cert_expiry=body.ex_cert_expiry, ex_zone=body.ex_zone,
        owner=body.owner, maint_due=body.maint_due,
    )
    db.add(r)
    db.commit()
    db.refresh(r)

    audit(db=db, action="device.create", target=r.name, user=me,
          detail={"adapter": r.adapter, "ip": r.ip, "port": r.port})
    await _reload_polling(db)
    msg_store.add("info", "system", f"新增设备：{r.name}",
                  f"{ADAPTERS[r.adapter]['label']} · {r.ip}:{r.port}",
                  {"to": "robots"})
    return _out(r)


@router.patch("/{device_id}", dependencies=[Depends(require_csrf)])
def update_device(
    device_id: int,
    body: DevicePatch,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin")),
) -> DeviceOut:
    r = db.get(Robot, device_id)
    if not r:
        raise NotFound("设备不存在")

    data = body.model_dump(exclude_none=True)
    if "password" in data:
        pwd = data.pop("password")
        r.password_cipher = seal(pwd or "", secret=get_settings().secret_key)
    if "adapter" in data and data["adapter"] not in ADAPTERS:
        raise BadRequest(f"未知协议 {data['adapter']}", code="BAD_ADAPTER")
    for k, v in data.items():
        setattr(r, k, v)
    db.commit()
    db.refresh(r)
    audit(db=db, action="device.update", target=r.name, user=me, detail=data)
    return _out(r)


@router.delete("/{device_id}", dependencies=[Depends(require_csrf)])
async def delete_device(
    device_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin")),
) -> dict:
    r = db.get(Robot, device_id)
    if not r:
        raise NotFound("设备不存在")
    if device_id == 1:
        raise BadRequest("主设备不能删除，只能停用", code="PRIMARY_DEVICE")
    db.delete(r)
    db.commit()
    audit(db=db, action="device.delete", target=r.name, user=me)
    await _reload_polling(db)
    return {"ok": True}


@router.post("/{device_id}/test", dependencies=[Depends(require_csrf)])
def test_device(
    device_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
) -> dict:
    """连通性测试：先 TCP，再（JCROB）读一次 status。不写任何数据。"""
    r = db.get(Robot, device_id)
    if not r:
        raise NotFound("设备不存在")

    # 只允许测试内网地址：乱填公网 IP 会被厂区工控防火墙当成扫描行为
    import ipaddress

    try:
        ip = ipaddress.ip_address(r.ip)
    except ValueError:
        raise BadRequest("只能填 IP 地址（不支持域名），例如 192.168.1.105", code="BAD_IP") from None
    if not (ip.is_private or ip.is_loopback):
        raise BadRequest("只允许测试内网地址（10/172.16-31/192.168），避免触发网安扫描告警",
                         code="PUBLIC_IP")

    result: dict[str, Any] = {"tcp": False, "http": False, "detail": ""}
    try:
        with socket.create_connection((r.ip, r.port), timeout=3):
            result["tcp"] = True
            result["detail"] = f"TCP {r.ip}:{r.port} 可连通"
    except OSError as exc:
        result["detail"] = f"TCP 连不上：{exc.__class__.__name__}"
        return result

    if r.adapter != "jcrob_http":
        result["detail"] += "；该协议适配器未实现，只能确认端口通"
        return result

    import json as _json
    import urllib.request as _req

    settings = get_settings()
    pwd = unseal(r.password_cipher or "", secret=settings.secret_key) or settings.jcrob_password
    base = f"http://{r.ip}:{r.port}/api/v1/status"
    basic = _req.HTTPBasicAuthHandler()
    basic.add_password(realm=None, uri=base, user=r.username or settings.jcrob_username,
                       passwd=pwd)
    opener = _req.build_opener(basic)
    try:
        with opener.open(base, timeout=4) as resp:
            data = _json.loads(resp.read().decode("utf-8", "replace"))
        result["http"] = True
        result["detail"] += f"；status 正常（电量 {data.get('battery', '—')}）"
    except Exception as exc:  # noqa: BLE001 - 探测失败要如实回报
        result["detail"] += f"；HTTP 状态读取失败：{exc.__class__.__name__}"
    return result


@router.post("/{device_id}/status-probe")
def probe_status(
    device_id: int,
    db: Session = Depends(get_db),
    cache=Depends(get_cache),
    _: User = Depends(get_current_user),
) -> dict:
    """非主设备的实时状态：按需建适配器查一次（主设备走轮询缓存）。"""
    r = db.get(Robot, device_id)
    if not r:
        raise NotFound("设备不存在")
    if device_id == 1:
        return {"source": "cache", "data": cache.as_dict()}

    settings = get_settings()
    try:
        adapter, _err = build_for(r, settings=settings)
    except AdapterNotSupported as exc:
        return {"source": "unsupported", "reason": exc.reason, "adapter": exc.adapter}

    import asyncio

    async def _read():
        try:
            return await adapter.snapshot()
        finally:
            await adapter.aclose()

    try:
        snap = asyncio.run(_read())
        return {"source": "live", "data": snap}
    except Exception as exc:  # noqa: BLE001
        return {"source": "error", "reason": f"{exc.__class__.__name__}: {exc}"}
