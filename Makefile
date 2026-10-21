.PHONY: help install test run lint web-dev deploy build

help:
	@echo "make install   安装后端依赖"
	@echo "make test      跑后端单元测试"
	@echo "make run       本地启动后端（mock 机器人）"
	@echo "make web-dev   前端开发服务器"
	@echo "make deploy    在 8.40 上 docker compose up -d"

install:
	cd server && python -m pip install -e ".[dev]"

test:
	cd server && python -m pytest tests -q

run:
	cd server && python -m uvicorn app.main:app --reload --port 8000

web-dev:
	cd web && npm run dev

deploy:
	cd deploy && cp -n env.example env || true && docker compose up -d --build
