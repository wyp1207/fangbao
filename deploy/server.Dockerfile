# 服务器镜像：先装依赖再拷代码，改代码不重装依赖
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY server/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir -e . \
    && pip install --no-cache-dir "uvicorn[standard]" gunicorn

COPY server/ /app/

RUN useradd -r -u 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# 单 worker 是刻意选择：状态缓存与后台循环都在进程内（方案 §3.1）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
