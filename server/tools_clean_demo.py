"""清掉演示/联调留下的假数据（只删测试痕迹，不动真实业务数据）。

为什么要有：甲方一打开就看到 "测试1" 摄像头、"升级测试：机器人失联" 告警、
8 字节假 AI 原图、pt_viewer_2026 之类测试账号——这不是功能问题，是可信度问题。

用法：python tools_clean_demo.py            # 预演，只打印
      python tools_clean_demo.py --apply    # 真删
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import or_

from app.db.session import SessionLocal
import app.models  # noqa: F401
from app.models.ai import AiResult
from app.models.alarm import AlarmRecord
from app.models.user import User
from app.models.video_source import VideoSource

TEST_USERS = ("mustchange", "mustchange2", "pt_viewer_2026", "pt_viewer2", "replay1",
              "pw_flow", "pw_hist", "safety_t", "totp_user", "gate_viewer", "lockme")
TEST_CAMERA_HINTS = ("测试1", "测试", "test")
FAKE_ALARM_HINTS = ("升级测试", "测试")


def main(apply: bool) -> int:
    plan: list[str] = []
    with SessionLocal() as db:
        users = db.query(User).filter(User.username.in_(TEST_USERS)).all()
        users += db.query(User).filter(User.username.like("pt_%")).all()
        plan.append(f"测试账号 {len(users)} 个: {[u.username for u in users]}")

        cams = db.query(VideoSource).all()
        bad_cams = [c for c in cams if any(h in (c.name or "") for h in TEST_CAMERA_HINTS)]
        plan.append(f"测试摄像头 {len(bad_cams)} 个: {[c.name for c in bad_cams]}")

        alarms = db.query(AlarmRecord).filter(
            or_(*[AlarmRecord.message.like(f"%{h}%") for h in FAKE_ALARM_HINTS])
        ).all()
        plan.append(f"测试告警 {len(alarms)} 条")

        results = db.query(AiResult).all()
        tiny = [r for r in results if r.image_path and
                (Path("data") / r.image_path).exists() and
                (Path("data") / r.image_path).stat().st_size < 1024]
        plan.append(f"假 AI 原图 {len(tiny)} 条（<1KB）")

        print("\n".join("  " + p for p in plan))
        if not apply:
            print("\n预演结束；加 --apply 才会删除")
            return 0

        for u in {u.id: u for u in users}.values():
            db.delete(u)
        for c in bad_cams:
            db.delete(c)
        for a in alarms:
            db.delete(a)
        for r in tiny:
            (Path("data") / r.image_path).unlink(missing_ok=True)
            db.delete(r)
        db.commit()
        print("\n已清理")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv))
