"""位姿/状态 WebSocket 推送（浏览器侧）。

为什么要有：前端原来是 1Hz 轮询，机器人位姿在大屏上像"瞬移"，3D 再炫也救不了。
这里每 200ms 把registry缓存里的最新位姿/状态推给前端（车端本身 1Hz，推得更快不产生新数据，
只是让前端拿到"最接近当前"的那一帧，配合插值看起来是连续的）。

鉴权：复用 httpOnly cookie 里的 JWT；未登录直接 1008 关闭。
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.core.security import decode_access_token

log = logging.getLogger(__name__)
router = APIRouter(tags=["ws"])

PUSH_INTERVAL_S = 0.2


def _user_from_cookie(websocket: WebSocket) -> dict | None:
    s = get_settings()
    token = websocket.cookies.get(s.cookie_name)
    if not token:
        token = websocket.query_params.get("token", "")
    if not token:
        return None
    return decode_access_token(token, secret=s.secret_key)


@router.websocket("/ws/robot/{robot_id}")
async def robot_ws(websocket: WebSocket, robot_id: int) -> None:
    payload = _user_from_cookie(websocket)
    if payload is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()

    from app.services.robot_runtime import registry

    last_sent = 0.0
    try:
        while True:
            rt = registry.get(robot_id)
            if rt is not None:
                snap = rt.cache.as_dict()
                pose = snap.get("pose") or {}
                status = snap.get("status") or {}
                info = snap.get("info") or {}
                msg = {
                    "type": "state",
                    "robot_id": robot_id,
                    "online": bool(snap.get("online")),
                    "age_s": snap.get("age_s"),
                    "pose": {
                        "x": pose.get("x"), "y": pose.get("y"),
                        "theta": pose.get("theta"), "theta_rad": pose.get("theta_rad"),
                    },
                    "status": {
                        "status": status.get("status"),
                        "located": status.get("located"),
                    },
                    "battery": info.get("battery"),
                }
                await websocket.send_text(json.dumps(msg, ensure_ascii=False))
            await asyncio.sleep(PUSH_INTERVAL_S)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.debug("WebSocket 推送结束 robot=%s", robot_id, exc_info=True)
    finally:
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
