# 服务器镜像：先装依赖再拷代码，改代码不重装依赖
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# ffmpeg 是录制与抓帧的硬依赖，不能省
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl tzdata ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY server/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir -e . \
    && pip install --no-cache-dir "uvicorn[standard]" gunicorn

COPY server/ /app/
# mock 适配器的契约样例在仓库根 contracts/，容器里 PROJECT_ROOT=/，
# 所以放到 /contracts；真机模式用不到，但演示/联调要有
COPY contracts/ /contracts/
COPY deploy/entrypoint.sh /app/entrypoint.sh

# 建用户、给脚本执行位、统一属主，都在切 USER 之前做完
# （切到 appuser 之后再 chmod 会 Operation not permitted）
# 数据目录必须先建好并归 appuser，否则挂载卷后容器写不进去
RUN useradd -r -u 10001 appuser \
    && mkdir -p /app/data/recordings /app/data/maps /app/logs \
    && chmod +x /app/entrypoint.sh \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=4 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# 单 worker 是刻意选择：状态缓存与后台循环都在进程内（方案 §3.1）
# 入口先跑 alembic upgrade head，迁移失败直接退出，不带半截库服务
CMD ["/app/entrypoint.sh"]
