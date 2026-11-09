"""云台预置位：海康 ISAPI presets。

接口（实测固件）：
- GET    /ISAPI/PTZCtrl/channels/{ch}/presets         列出
- PUT    /ISAPI/PTZCtrl/channels/{ch}/presets/{id}    把当前位置存为该预置位（同号即覆盖）
- PUT    /ISAPI/PTZCtrl/channels/{ch}/presets/{id}/goto  转到该预置位
- DELETE /ISAPI/PTZCtrl/channels/{ch}/presets/{id}    删除

海康/大华一致：预置位是 1–256 的编号，每个编号存一个位置 + 一个名字；
不提供"自动取号"这种语义，取号只是 UI 的默认值，最终由用户确认后写入。
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from app.services import ptz

log = logging.getLogger(__name__)

MIN_PRESET_ID = 1
MAX_PRESET_ID = 256


def valid_preset_id(preset_id: object) -> bool:
    return isinstance(preset_id, int) and MIN_PRESET_ID <= preset_id <= MAX_PRESET_ID


def preset_id_error() -> str:
    return f"预置位编号必须是 {MIN_PRESET_ID}–{MAX_PRESET_ID} 之间的整数"


def next_free_id(items: list[dict]) -> int | None:
    """默认编号：最小可用号；1–256 用满时返回 None（前端要求用户删一个或手填覆盖）。"""
    used = {int(i["preset_id"]) for i in items if str(i.get("preset_id", "")).isdigit()}
    for preset_id in range(MIN_PRESET_ID, MAX_PRESET_ID + 1):
        if preset_id not in used:
            return preset_id
    return None


def _local(tag: str) -> str:
    """去掉 XML 命名空间：ISAPI 返回带 xmlns，ElementTree 的 tag 会变成 {ns}PTZPreset。"""
    return tag.rsplit("}", 1)[-1]


def parse_presets(text: str) -> list[dict]:
    """解析 ISAPI 预置位列表。

    真实固件（X30 上的海康双光谱，2026-11 实测）返回的是：
        <PTZPreset><enabled>true</enabled><id>1</id>
          <presetName>预置点 1</presetName>...
    既不是 `<name>`，字段顺序也不是 id 在前；老正则要求 `<id>` 紧跟 `<PTZPreset>`，
    结果永远解析出空列表（页面上"一个预置位都没有"）。这里按节点名取值。
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        # 少数非标准固件：退回宽松正则，兼容 <name> 与 <presetName>
        items = []
        for pid, name in re.findall(
                r"<id>\s*(\d+)\s*</id>.*?<(?:presetName|name)>\s*([^<]*)</(?:presetName|name)>",
                text, re.S):
            if MIN_PRESET_ID <= int(pid) <= MAX_PRESET_ID:
                items.append({"preset_id": int(pid), "name": name.strip()})
        return sorted(items, key=lambda x: x["preset_id"])

    items = []
    for el in root.iter():
        if _local(el.tag) != "PTZPreset":
            continue
        fields = {_local(child.tag): (child.text or "").strip() for child in el}
        raw_id = fields.get("id", "")
        if not raw_id.isdigit():
            continue
        preset_id = int(raw_id)
        if not MIN_PRESET_ID <= preset_id <= MAX_PRESET_ID:
            continue
        name = fields.get("presetName") or fields.get("name") or ""
        items.append({"preset_id": preset_id, "name": name})
    # 同一 id 重复出现（部分固件会把无效位也列出来）只保留第一条
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x["preset_id"]):
        if it["preset_id"] in seen:
            continue
        seen.add(it["preset_id"])
        out.append(it)
    return out


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
        return True, "", parse_presets(r.text)
    except Exception as exc:  # noqa: BLE001
        log.warning("列出预置位失败", exc_info=True)
        return False, f"{exc.__class__.__name__}: {exc}", []


def save_preset(preset_id: int, name: str) -> tuple[bool, str]:
    ok, why = ptz.available()
    if not ok:
        return False, why
    if not valid_preset_id(preset_id):
        return False, preset_id_error()
    safe_name = escape((name or "").strip()[:32])
    # 字段名必须是 presetName：这台固件对 <name> 返回 200 但直接忽略（实测 2026-11）
    body = (f"<PTZPreset><id>{preset_id}</id><presetName>{safe_name}</presetName>"
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
    if not valid_preset_id(preset_id):
        return False, preset_id_error()
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
    if not valid_preset_id(preset_id):
        return False, preset_id_error()
    try:
        with ptz._client(ptz._cfg()) as cli:
            r = cli.delete(_url(f"/presets/{preset_id}"))
        if r.status_code >= 300:
            return False, f"HTTP {r.status_code}"
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{exc.__class__.__name__}: {exc}"
