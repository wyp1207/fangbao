"""测试必须先设环境变量再 import app：db engine 在 import 时就建了。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = ROOT / "data"
_TMP.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("JC_ENV", "test")
os.environ["JC_DB_URL"] = f"sqlite:///{(_TMP / f'test-{os.getpid()}.db').as_posix()}"
os.environ["JC_ROBOT_MODE"] = "mock"
os.environ["JC_BOOTSTRAP_ADMIN"] = "admin"
os.environ["JC_BOOTSTRAP_PASSWORD"] = "admin123"
os.environ["JC_FORCE_PASSWORD_CHANGE"] = "0"   # 测试里不要被强制改密拦住
os.environ["JC_JCROB_FIXTURES"] = str(ROOT.parent / "contracts" / "jcrob" / "fixtures")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_client(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    csrf = r.json()["csrf_token"]
    client.headers.update({"X-CSRF-Token": csrf})
    return client
