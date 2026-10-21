# 前端：多阶段构建。
# 仓库里已经有 npm 生成的 package-lock.json，所以直接用 npm ci 保证可复现，
# 不引 pnpm（本机没有 pnpm，多一个包管理器就多一套锁文件）。
FROM node:20-alpine AS build

WORKDIR /app

COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY web/ ./
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/nginx/default.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
