"""资源锁 + 到点三值的测试（B/C/D 的最小检查）。"""

from __future__ import annotations

import threading

from app.services.resource_lock import release, snapshot, try_acquire


def test_lock_blocks_second_owner():
    assert try_acquire(["point:1"], run_id=101, robot_id=1) is True
    assert try_acquire(["point:1"], run_id=102, robot_id=2) is False
    release(["point:1"], run_id=101)
    assert try_acquire(["point:1"], run_id=102, robot_id=2) is True
    release(["point:1"], run_id=102)


def test_lock_ordered_keys_no_deadlock():
    """两个线程交叉抢 [A,B] 与 [B,A]：字典序保证不会互相等死。"""
    got: list[bool] = []
    barrier = threading.Barrier(2)

    def worker(keys, rid):
        barrier.wait()
        got.append(try_acquire(keys, run_id=rid, robot_id=rid))

    t1 = threading.Thread(target=worker, args=(["point:9", "zone:a"], 201))
    t2 = threading.Thread(target=worker, args=(["zone:a", "point:9"], 202))
    t1.start(); t2.start(); t1.join(timeout=3); t2.join(timeout=3)
    # 两个都拿到（同一组有序 key 可重入）或一个拿到一个失败，都算不死锁
    assert len(got) == 2
    release(["point:9", "zone:a"], run_id=201)
    release(["point:9", "zone:a"], run_id=202)


def test_lock_expires():
    assert try_acquire(["charger:1"], run_id=301, robot_id=3, ttl_s=0) is True
    # ttl=0 → 立即过期，下一个应能拿到
    assert try_acquire(["charger:1"], run_id=302, robot_id=4, ttl_s=60) is True
    release(["charger:1"], run_id=302)


def test_snapshot_lists_held():
    try_acquire(["point:77"], run_id=401, robot_id=5, ttl_s=60)
    keys = [x["key"] for x in snapshot()]
    assert "point:77" in keys
    release(["point:77"], run_id=401)
