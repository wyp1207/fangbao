"""平台配置。所有值走环境变量（前缀 JC_）或 .env，不硬编码凭据。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = SERVER_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JC_", env_file=str(SERVER_ROOT / ".env"), extra="ignore"
    )

    env: str = "dev"
    app_name: str = "防爆机器人巡检平台"
    api_prefix: str = "/api/v1"
    secret_key: str = Field(default="dev-only-secret-change-me-please-32b")
    jwt_ttl_minutes: int = 240
    cookie_name: str = "jc_token"

    # Cookie 的 Secure 标记：None = 按实际协议自动判断（https 才加 Secure）。
    # 内网 http 部署时如果无脑加 Secure，浏览器不会回传 cookie，
    # 表现就是"登录成功但所有接口 401"。
    cookie_secure: bool | None = None
    csrf_cookie: str = "jc_csrf"

    db_url: str = f"sqlite:///{SERVER_ROOT / 'data' / 'app.db'}"

    bootstrap_admin: str = "admin"
    bootstrap_password: str = "admin123"
    # 初始管理员是否强制改密：生产必须开；测试环境关掉，否则夹具没法跑
    force_password_change: bool = True
    # 生产建议关掉 /docs 与 /openapi.json（信息泄露面）
    docs_enabled: bool = True

    # 对外访问地址（手机端链接/推送里用），例如 http://192.168.8.40:8099
    public_base_url: str = ""
    # /metrics 抓取口令；留空则只允许内网访问
    metrics_token: str = ""
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # 云深处 X30（导航主机本体监控协议）
    x30_host: str = "192.168.1.106"
    x30_port: int = 30000
    x30_timeout: float = 15.0

    # 机器人
    robot_mode: str = "mock"
    # 转流服务（MediaMTX 等）的 HLS 前缀；空 = 没配转流，前端不做假播放
    video_hls_base: str = ""
    # 可选的中继地址（go2rtc/MediaMTX），配置后所有取流都走它，避免直连相机多开会话
    video_relay_url: str = ""
    # go2rtc 的 HTTP 地址（如 http://127.0.0.1:1984）；配了就用它的 MSE/WebRTC 播放器
    go2rtc_base: str = ""

    # 浏览器侧的 go2rtc 地址。部署时 nginx 反代 /go2rtc/ 到 go2rtc，
    # 这里填 /go2rtc，前端就用同源相对路径，不用暴露 1984 端口、也没有跨域问题
    go2rtc_public_base: str = ""
    # MJPEG 转码宽度：太小会糊、太大吃 CPU
    video_scale_width: int = 1280
    # 录像开关：保留策略未定前默认关闭，避免盘被写满
    recording_enabled: bool = True
    record_keep_days: int = 30
    record_max_gb: int = 800
    record_min_free_gb: int = 5
    jcrob_base_url: str = "http://127.0.0.1:3546"
    jcrob_ws_url: str = "ws://127.0.0.1:3547"
    jcrob_username: str = "admin"
    jcrob_password: str = "admin"
    jcrob_token: str = ""
    jcrob_http_timeout: float = 3.0
    jcrob_poll_interval: float = 1.0
    jcrob_fixtures: str = str(PROJECT_ROOT / "contracts" / "jcrob" / "fixtures")

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    @property
    def is_dev(self) -> bool:
        return self.env.lower() in {"dev", "local", "test"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


_DEFAULT_SECRETS = {"", "dev-only-secret-change-me-please-32b", "please-change-this-to-a-random-32-byte-string"}


def assert_production_safe() -> None:
    """prod 下不允许默认密钥/默认口令启动。

    默认 JWT 密钥等于把签发权公开：谁都能签一个 sub=1 的 admin token。
    """
    st = get_settings()
    if st.env not in ("prod", "production"):
        return
    problems = []
    if st.secret_key in _DEFAULT_SECRETS or len(st.secret_key) < 32:
        problems.append("JC_SECRET_KEY 仍是默认值或太短（至少 32 字节）")
    if st.bootstrap_password in ("admin123", "please-change-on-first-login"):
        problems.append("JC_BOOTSTRAP_PASSWORD 仍是默认值")
    if problems:
        raise RuntimeError("生产环境配置不安全，拒绝启动：" + "；".join(problems))
