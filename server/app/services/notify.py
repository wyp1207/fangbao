"""告警外发：把告警推到企业微信 / 钉钉 / 通用 webhook / 邮件。

为什么要队列：投递是网络动作，不能卡住 1 秒一次的轮询循环。
`on_alarm()` 只入队，后台线程按通道逐个发，失败重试 2 次并落库。

静默策略：同一通道对**同一指标**在 N 分钟内只发一条（N 可按通道配），
否则电量告警会每轮刷一次，值班的人会把群消息免打扰，等于没告警。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import queue
import smtplib
import threading
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from typing import Any

from app.core.config import get_settings

import httpx
import sqlalchemy as sa

log = logging.getLogger(__name__)

LEVEL_ORDER = {"warn": 1, "critical": 2}

TYPE_LABELS = {
    "wecom": "企业微信机器人",
    "dingtalk": "钉钉机器人",
    "generic": "通用 Webhook",
    "email": "邮件（SMTP）",
    "sms": "短信/语音网关（HTTP）",
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


def _payload_sms(alarm: dict, cfg: dict) -> dict:
    """短信/语音网关：不同厂商字段不同，这里用最通用的 to/text + alarm 原文。

    对接时把 url 指到厂商的 HTTP 接口；若厂商要签名，用 cfg["headers"] 传。
    """
    to = cfg.get("to") or []
    if isinstance(to, str):
        to = [x.strip() for x in to.split(",") if x.strip()]
    return {"to": to, "text": _text(alarm), "alarm": alarm}


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
    elif channel.type == "sms":
        body = _payload_sms(alarm, cfg)
    else:
        body = _payload_generic(alarm, cfg)

    headers = {"Content-Type": "application/json"}
    headers.update(cfg.get("headers") or {})

    # 签名：接收方用同一 secret 校验，能判断"是不是我们发的、有没有被改"
    secret = (cfg.get("secret") or "").strip() or get_settings().secret_key
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    headers["X-Jcrob-Timestamp"] = ts
    headers["X-Jcrob-Signature"] = f"sha256={sig}"

    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(url, content=raw, headers=headers)
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
        last_escalate = 0.0
        while not self._stop.is_set():
            try:
                alarm_id, alarm = self._q.get(timeout=1.0)
            except queue.Empty:
                alarm_id, alarm = None, None

            if alarm is not None:
                try:
                    self._dispatch(alarm_id, alarm)
                except Exception:  # noqa: BLE001
                    log.exception("通知分发失败")

            # 每分钟：该升级的告警 + 失败的投递重试
            if time.time() - last_escalate > 60:
                last_escalate = time.time()
                try:
                    self.escalate_once()
                except Exception:  # noqa: BLE001
                    log.exception("告警升级失败")
                try:
                    n = self.retry_once()
                    if n:
                        log.info("通知重试成功 %s 条", n)
                except Exception:  # noqa: BLE001
                    log.exception("通知重试失败")

    def _dispatch(self, alarm_id: int, alarm: dict) -> None:
        from app.models.notify import NotifyChannel, NotifyLog

        level = LEVEL_ORDER.get(alarm.get("level", "warn"), 1)
        with self._session_factory() as db:  # type: ignore[misc]
            channels = (
                db.query(NotifyChannel)
                .filter(NotifyChannel.enabled.is_(True), NotifyChannel.tier == 1)
                .all()
            )
            for ch in channels:
                if level < LEVEL_ORDER.get(ch.min_level, 2):
                    continue

                # 静默期只压制"同级别重复"，且严重告警永不静默：
                # 低级别进了静默期，后面来的急停/离线照样要发出去
                metric = str(alarm.get("metric") or "unknown")
                level_key = str(alarm.get("level") or "warn")
                key = (ch.id, metric, level_key)
                now = time.time()
                silence = max(ch.min_interval_min, 0) * 60
                if level_key != "critical" and now - self._last_sent.get(key, 0) < silence:
                    continue

                ok, status = self._deliver_with_retry(ch, alarm)
                self._last_sent[key] = now
                db.add(NotifyLog(
                    ts=datetime.now(), channel_id=ch.id, channel_name=ch.name,
                    alarm_id=alarm_id, payload=_text(alarm)[:500],
                    ok=ok, status=status[:60], error=None if ok else status[:500],
                    payload_json=None if ok else json.dumps(alarm, ensure_ascii=False)[:4000],
                    attempts=1,
                    next_retry_at=None if ok else datetime.now() + timedelta(seconds=60),
                ))
                db.commit()

    def escalate_once(self) -> dict:
        """critical 未确认超过 N 分钟 → 发给值班长（tier=2），并标记已升级。

        只升级一次：不能每轮都发，否则值班长同样会免打扰。
        """
        from app.models.alarm import AlarmRecord
        from app.models.notify import NotifyChannel, NotifyLog

        try:
            from app.api.v1.settings import load_all
            cfg = load_all()
        except Exception:  # noqa: BLE001
            cfg = {}
        if not bool(cfg.get("notify.escalate_enabled", True)):
            return {"escalated": 0}
        after_min = int(cfg.get("notify.escalate_after_min", 5))
        cutoff = datetime.now() - timedelta(minutes=after_min)

        escalated = 0
        with self._session_factory() as db:  # type: ignore[misc]
            pending = (
                db.query(AlarmRecord)
                .filter(
                    AlarmRecord.level == "critical",
                    AlarmRecord.acked_at.is_(None),
                    AlarmRecord.closed_at.is_(None),
                    AlarmRecord.escalated_at.is_(None),
                    # 搁置中的告警不升级（和工单侧一致：检修/标定期间别叫人）
                    sa.or_(AlarmRecord.shelved_until.is_(None),
                           AlarmRecord.shelved_until <= datetime.now()),
                    AlarmRecord.started_at <= cutoff,
                )
                .all()
            )
            if not pending:
                return {"escalated": 0}

            chiefs = (
                db.query(NotifyChannel)
                .filter(NotifyChannel.enabled.is_(True), NotifyChannel.tier == 2)
                .all()
            )

            if not chiefs:
                # 没配置升级通道时不要标记 escalated：否则以后补建通道也不会再升级
                return {"escalated": 0, "reason": "没有 tier=2 通道"}

            for alarm in pending:
                alarm.escalated_at = datetime.now()
                payload = alarm.to_dict()
                for ch in chiefs:
                    ok, status = self._deliver_with_retry(ch, payload)
                    db.add(NotifyLog(
                        ts=datetime.now(), channel_id=ch.id, channel_name=ch.name,
                        alarm_id=alarm.id, payload=_text(payload)[:500],
                        ok=ok, status=("升级: " + status)[:60],
                        error=None if ok else status[:500],
                    ))
                escalated += 1
            db.commit()
        return {"escalated": escalated}

    def retry_once(self) -> int:
        """重投失败的投递（最多 3 次，间隔 2/4 分钟）。

        为什么要落库重试：外发通道（企业微信/钉钉/邮件）抖动很常见，
        只在内存里重试，进程一重启就丢了，接收方永远收不到那条告警。
        """
        from app.models.notify import NotifyChannel, NotifyLog

        now = datetime.now()
        done = 0
        with self._session_factory() as db:  # type: ignore[misc]
            rows = (
                db.query(NotifyLog)
                .filter(NotifyLog.ok.is_(False),
                        NotifyLog.attempts < 3,
                        NotifyLog.next_retry_at.isnot(None),
                        NotifyLog.next_retry_at <= now,
                        NotifyLog.payload_json.isnot(None))
                .limit(20)
                .all()
            )
            for row in rows:
                ch = db.get(NotifyChannel, row.channel_id)
                if ch is None or not ch.enabled:
                    row.next_retry_at = None
                    continue
                try:
                    alarm = json.loads(row.payload_json or "{}")
                except Exception:  # noqa: BLE001
                    row.next_retry_at = None
                    continue
                ok, status = send_once(ch, alarm)
                row.attempts += 1
                row.ts = now
                row.ok = ok
                row.status = ("重试: " + status)[:64]
                row.error = None if ok else status[:500]
                row.next_retry_at = None if ok else now + timedelta(minutes=2 * row.attempts)
                if ok:
                    done += 1
            db.commit()
        return done

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


def push_text(text: str, *, level: str = "warn") -> int:
    """推一条普通文本到所有启用的 tier=1 通道（派单、提醒用）。

    和告警共用通道配置，不再单独维护一套推送设置。
    """
    from app.models.notify import NotifyChannel

    dispatcher = _dispatcher
    if dispatcher is None:
        return 0
    sent = 0
    with dispatcher._session_factory() as db:  # noqa: SLF001 - 同模块内部使用
        channels = db.query(NotifyChannel).filter(
            NotifyChannel.enabled.is_(True), NotifyChannel.tier == 1).all()
        for ch in channels:
            alarm = {"id": None, "metric": "work_order", "level": level,
                     "message": text, "value": None, "text": text}
            ok, _status = send_once(ch, alarm)
            if ok:
                sent += 1
    return sent
