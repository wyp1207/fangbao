"""告警外发：把告警推到企业微信 / 钉钉 / 通用 webhook / 邮件。

为什么要队列：投递是网络动作，不能卡住 1 秒一次的轮询循环。
`on_alarm()` 只入队，后台线程按通道逐个发，失败重试 2 次并落库。

静默策略：同一通道对**同一指标**在 N 分钟内只发一条（N 可按通道配），
否则电量告警会每轮刷一次，值班的人会把群消息免打扰，等于没告警。
"""

from __future__ import annotations

import json
import logging
import queue
import smtplib
import threading
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from typing import Any

import httpx

log = logging.getLogger(__name__)

LEVEL_ORDER = {"warn": 1, "critical": 2}

TYPE_LABELS = {
    "wecom": "企业微信机器人",
    "dingtalk": "钉钉机器人",
    "generic": "通用 Webhook",
    "email": "邮件（SMTP）",
}


# ---------------- 报文构造 ----------------

def _text(alarm: dict) -> str:
    level = "严重" if alarm.get("level") == "critical" else "提醒"
    ts = (alarm.get("started_at") or "").replace("T", " ")[:19]
    return (
        f"【{level}】{alarm.get('message', '')}\n"
        f"指标：{alarm.get('metric', '')}\n"
        f"时间：{ts}\n"
        f"编号：#{alarm.get('id', '')}"
    )


def _payload_wecom(alarm: dict, cfg: dict) -> dict:
    return {"msgtype": "markdown", "markdown": {"content": _text(alarm)}}


def _payload_dingtalk(alarm: dict, cfg: dict) -> dict:
    return {"msgtype": "markdown",
            "markdown": {"title": f"告警 #{alarm.get('id')}", "text": _text(alarm)}}


def _payload_generic(alarm: dict, cfg: dict) -> dict:
    return {"event": "alarm", "alarm": alarm, "text": _text(alarm)}


# ---------------- 发送 ----------------

def _send_http(channel, alarm: dict, cfg: dict) -> tuple[bool, str]:
    url = (cfg.get("url") or "").strip()
    if not url:
        return False, "未配置 URL"

    if channel.type == "wecom":
        body = _payload_wecom(alarm, cfg)
    elif channel.type == "dingtalk":
        body = _payload_dingtalk(alarm, cfg)
    else:
        body = _payload_generic(alarm, cfg)

    headers = {"Content-Type": "application/json"}
    headers.update(cfg.get("headers") or {})

    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(url, json=body, headers=headers)
        # 企业微信/钉钉都用 errcode=0 表示成功，HTTP 200 不代表业务成功
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            data = {}
        errcode = data.get("errcode")
        if resp.status_code >= 300:
            return False, f"HTTP {resp.status_code}: {resp.text[:160]}"
        if errcode not in (None, 0):
            return False, f"errcode={errcode} {data.get('errmsg', '')}"
        return True, f"HTTP {resp.status_code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{exc.__class__.__name__}: {exc}"


def _send_email(channel, alarm: dict, cfg: dict) -> tuple[bool, str]:
    host = cfg.get("host") or ""
    port = int(cfg.get("port") or 25)
    to = cfg.get("to") or []
    if isinstance(to, str):
        to = [x.strip() for x in to.split(",") if x.strip()]
    if not host or not to:
        return False, "未配置 SMTP 服务器或收件人"

    msg = MIMEText(_text(alarm), "plain", "utf-8")
    msg["Subject"] = f"[巡检告警] {alarm.get('message', '')[:60]}"
    msg["From"] = cfg.get("sender") or cfg.get("user") or "jcrob@localhost"
    msg["To"] = ", ".join(to)

    try:
        if cfg.get("tls"):
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            if cfg.get("starttls"):
                server.starttls()
        if cfg.get("user"):
            server.login(cfg["user"], cfg.get("password") or "")
        server.sendmail(msg["From"], to, msg.as_string())
        server.quit()
        return True, f"已发送给 {len(to)} 人"
    except Exception as exc:  # noqa: BLE001
        return False, f"{exc.__class__.__name__}: {exc}"


def send_once(channel, alarm: dict) -> tuple[bool, str]:
    try:
        cfg = json.loads(channel.config_json or "{}")
    except Exception:  # noqa: BLE001
        return False, "config_json 不是合法 JSON"
    if channel.type == "email":
        return _send_email(channel, alarm, cfg)
    return _send_http(channel, alarm, cfg)


# ---------------- 调度器 ----------------

class NotifyDispatcher:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory
        self._q: queue.Queue[tuple[int, dict]] = queue.Queue(maxsize=500)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_sent: dict[tuple[int, str], float] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def on_alarm(self, alarm: dict) -> None:
        """只入队，绝不阻塞调用方（轮询线程）。"""
        try:
            self._q.put_nowait((alarm.get("id") or 0, alarm))
        except queue.Full:
            log.warning("通知队列已满，丢弃告警 #%s", alarm.get("id"))

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                alarm_id, alarm = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self._dispatch(alarm_id, alarm)
            except Exception:  # noqa: BLE001
                log.exception("通知分发失败")

    def _dispatch(self, alarm_id: int, alarm: dict) -> None:
        from app.models.notify import NotifyChannel, NotifyLog

        level = LEVEL_ORDER.get(alarm.get("level", "warn"), 1)
        with self._session_factory() as db:  # type: ignore[misc]
            channels = db.query(NotifyChannel).filter(NotifyChannel.enabled.is_(True)).all()
            for ch in channels:
                if level < LEVEL_ORDER.get(ch.min_level, 2):
                    continue

                key = (ch.id, str(alarm.get("metric") or "unknown"))
                now = time.time()
                if now - self._last_sent.get(key, 0) < max(ch.min_interval_min, 0) * 60:
                    continue

                ok, status = self._deliver_with_retry(ch, alarm)
                self._last_sent[key] = now
                db.add(NotifyLog(
                    ts=datetime.now(), channel_id=ch.id, channel_name=ch.name,
                    alarm_id=alarm_id, payload=_text(alarm)[:500],
                    ok=ok, status=status[:60], error=None if ok else status[:500],
                ))
                db.commit()

    def _deliver_with_retry(self, channel, alarm: dict, attempts: int = 3):
        last = (False, "")
        for i in range(attempts):
            ok, status = send_once(channel, alarm)
            if ok:
                return True, status
            last = (ok, status)
            time.sleep(min(2 ** i, 4))
        return last


_dispatcher: NotifyDispatcher | None = None


def init(session_factory) -> NotifyDispatcher:
    global _dispatcher
    _dispatcher = NotifyDispatcher(session_factory)
    _dispatcher.start()
    return _dispatcher


def on_alarm(alarm: dict) -> None:
    if _dispatcher is not None:
        _dispatcher.on_alarm(alarm)
