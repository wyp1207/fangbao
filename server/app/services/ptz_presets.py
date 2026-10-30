"""云台预置位：海康 ISAPI presets。

接口（实测固件）：
- GET    /ISAPI/PTZCtrl/channels/{ch}/presets         列出
- PUT    /ISAPI/PTZCtrl/channels/{ch}/presets/{id}    把当前位置存为该预置位
- PUT    /ISAPI/PTZCtrl/channels/{ch}/presets/{id}/goto  转到该预置位
- DELETE /ISAPI/PTZCtrl/channels/{ch}/presets/{id}    删除
"""

from __future__ import annotations

import logging
import re

from app.services import ptz

log = logging.getLogger(__name__)


def _url(path: str) -> str:
    c = ptz._cfg()
    return f"http://{c['host']}/ISAPI/PTZCtrl/channels/{c['channel']}{path}"


def list_presets() -> tuple[bool, str, list[dict]]:
    ok, why = ptz.available()
    if not ok:
        return False, why, []
    try:
        with ptz._client(ptz._cfg()) as cli:
            r = cli.get(_url("/presets"))
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}", []
        items = re.findall(
            r"<PTZPreset[^>]*>\s*<id>(\d+)</id>\s*(?:<name>([^<]*)</name>)?", r.text)
        return True, "", [{"preset_id": int(i), "name": (n or "").strip()} for i, n in items]
    except Exception as exc:  # noqa: BLE001
        log.warning("列出预置位失败", exc_info=True)
        return False, f"{exc.__class__.__name__}: {exc}", []


def save_preset(preset_id: int, name: str) -> tuple[bool, str]:
    ok, why = ptz.available()
    if not ok:
        return False, why
    body = (f"<PTZPreset><id>{preset_id}</id><name>{name}</name>"
            f"<enabled>true</enabled></PTZPreset>")
    try:
        with ptz._client(ptz._cfg()) as cli:
            r = cli.put(_url(f"/presets/{preset_id}"), content=body.encode(),
                        headers={"Content-Type": "application/xml"})
        if r.status_code >= 300:
            return False, f"HTTP {r.status_code}: {r.text[:120]}"
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{exc.__class__.__name__}: {exc}"


def goto_preset(preset_id: int) -> tuple[bool, str]:
    ok, why = ptz.available()
    if not ok:
        return False, why
    try:
        with ptz._client(ptz._cfg()) as cli:
            r = cli.put(_url(f"/presets/{preset_id}/goto"),
                        content=b"<PTZPreset><id>%d</id></PTZPreset>" % preset_id,
                        headers={"Content-Type": "application/xml"})
        if r.status_code >= 300:
            return False, f"HTTP {r.status_code}: {r.text[:120]}"
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{exc.__class__.__name__}: {exc}"


def delete_preset(preset_id: int) -> tuple[bool, str]:
    ok, why = ptz.available()
    if not ok:
        return False, why
    try:
        with ptz._client(ptz._cfg()) as cli:
            r = cli.delete(_url(f"/presets/{preset_id}"))
        if r.status_code >= 300:
            return False, f"HTTP {r.status_code}"
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{exc.__class__.__name__}: {exc}"
