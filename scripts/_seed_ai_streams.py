# -*- coding: utf-8 -*-
"""种子 AI 视频流：往本地 SQLite 的 ai_stream 写入四路（幂等 upsert）。

为什么单独一个脚本：现场相机口令不能进代码/仓库，也不能进日志。
所以四路流的地址全部在这里拼，口令只从环境变量读，打印一律打码。

环境变量（缺一个就报错退出，不会静默写半套数据）：
    CAM64_PASS   192.168.1.64 海康双光谱云台 admin 口令（visible/thermal 共用）
    CAM65_PASS   192.168.1.65 固定枪机 admin 口令（fixed）
    CAM105_PASS  192.168.1.105:8554/test 的 ysc 口令（现场为单引号字面 ' ）

用法：
    python scripts/_seed_ai_streams.py               # 默认写 server/data/app.db
    python scripts/_seed_ai_streams.py --db X.db     # 指定库
    python scripts/_seed_ai_streams.py --dry-run     # 只打印将要写的行（口令已打码）

幂等：唯一键 (robot_id, stream_type, role)。已存在则就地 UPDATE，
      不改 id、不产生第二条；重复执行结果一致。
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "server" / "data" / "app.db"

# (robot_id, stream_type, role, host, port, user_env, pwd_env, path, channel, resolution, fps, codec, note)
STREAMS = [
    (2, "visible", "main", "192.168.1.64", 554, "CAM64_USER", "CAM64_PASS",
     "/h264/ch1/main/av_stream", "101", "2688x1520", 25, "h264", "海康双光谱云台·可见光主码流"),
    (2, "thermal", "main", "192.168.1.64", 554, "CAM64_USER", "CAM64_PASS",
     "/h264/ch1/main/av_stream", "201", "1280x960", 25, "h264", "海康双光谱云台·热成像主码流"),
    (2, "front", "main", "192.168.1.105", 8554, "CAM105_USER", "CAM105_PASS",
     "/test", "101", "640x480", 30, "h264", "X30 机载广角（RTSP 源，非海康 ISAPI）"),
    (99, "fixed", "main", "192.168.1.65", 554, "CAM65_USER", "CAM65_PASS",
     "/h264/ch1/main/av_stream", "101", "2560x1440", 25, "h264", "固定枪机 DS-2CD1245-LA"),
]

DEFAULT_USER = {"CAM64_USER": "admin", "CAM65_USER": "admin", "CAM105_USER": "ysc"}


def mask(url: str) -> str:
    """rtsp://u:p@h/p → rtsp://u:***@h/p。日志里永远只出现这个。"""
    u = urlsplit(url)
    if u.password is None:
        return url
    return url.replace(f":{u.password}@", ":***@", 1)


def build_url(user: str, pwd: str, host: str, port: int, path: str) -> str:
    """拼 rtsp 地址。

    这里故意**不做百分号编码**：抓图接口用 urlsplit().password 直接取口令去算
    Digest，而 urlsplit 不会 unquote。若把单引号编成 %27，相机收到的是 "%27"，
    认证必然失败。所以只对会破坏 URL 结构的字符（@ : /）做编码，保留原字节。
    """
    safe_pwd = pwd.replace("/", "%2F").replace("@", "%40").replace(":", "%3A")
    url = f"rtsp://{user}:{safe_pwd}@{host}:{port}{path}"
    back = urlsplit(url)
    if back.username != user or (back.password or "") != pwd:
        raise SystemExit(
            f"口令里含无法安全放入 URL 的字符（user={user} host={host}）"
            "：请在库里改用其它承载方式，不要在这里丢掉口令"
        )
    return url


def upsert(db: sqlite3.Connection, row: tuple) -> str:
    (robot_id, stream_type, role, host, port, user_env, pwd_env,
     path, channel, res, fps, codec, note) = row

    user = os.environ.get(user_env) or DEFAULT_USER[user_env]
    pwd = os.environ.get(pwd_env, "")
    if not pwd:
        raise SystemExit(f"缺少环境变量 {pwd_env}（{host} 的口令），不写库")
    url = build_url(user, pwd, host, port, path)
    # ORM 的 default 只在 ORM 插入时生效，这里裸 SQL 必须自己给时间
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur = db.execute(
        "SELECT id FROM ai_stream WHERE robot_id=? AND stream_type=? AND role=?",
        (robot_id, stream_type, role),
    )
    existing = cur.fetchone()
    if existing:
        db.execute(
            "UPDATE ai_stream SET rtsp_url=?, channel=?, resolution=?, fps=?, codec=?,"
            " status='active', note=?, created_at=COALESCE(created_at, ?) WHERE id=?",
            (url, channel, res, fps, codec, note, now, existing[0]),
        )
        action = f"updated id={existing[0]}"
    else:
        cur = db.execute(
            "INSERT INTO ai_stream (robot_id, stream_type, role, rtsp_url, channel,"
            " resolution, fps, codec, status, note, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,'active',?,?)",
            (robot_id, stream_type, role, url, channel, res, fps, codec, note, now),
        )
        action = f"inserted id={cur.lastrowid}"
    print(f"  robot={robot_id} {stream_type}/{role} ch={channel} {mask(url)} → {action}")
    return action


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"库不存在：{db_path}", file=sys.stderr)
        return 2

    missing = [env for _, _, _, _, _, _, env, *_ in STREAMS if not os.environ.get(env)]
    if missing and not args.dry_run:
        print(f"缺少环境变量：{', '.join(sorted(set(missing)))}（口令只走环境变量）",
              file=sys.stderr)
        return 2

    with sqlite3.connect(db_path) as db:
        cols = {r[1] for r in db.execute("PRAGMA table_info(ai_stream)")}
        need = {"robot_id", "stream_type", "role", "rtsp_url", "channel", "status"}
        if not need <= cols:
            print(f"ai_stream 表结构不对，缺 {need - cols}", file=sys.stderr)
            return 3
        for row in STREAMS:
            if args.dry_run:
                host, port, path, channel = row[3], row[4], row[7], row[8]
                print(f"  would upsert robot={row[0]} {row[1]}/{row[2]} "
                      f"rtsp://{DEFAULT_USER[row[5]]}:***@{host}:{port}{path} ch={channel}")
            else:
                upsert(db, row)
        if args.dry_run:
            db.rollback()
            print("dry-run：已回滚，库未改动")
        else:
            db.commit()

    if not args.dry_run:
        with sqlite3.connect(db_path) as db:
            n = db.execute("SELECT COUNT(*) FROM ai_stream").fetchone()[0]
            print(f"ai_stream 现有 {n} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
