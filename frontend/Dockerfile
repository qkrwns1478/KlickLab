# KlickLab 대시보드 (Vite 정적 빌드 + nginx). 빌드 컨텍스트는 frontend/ 이다.
#   docker build -t klicklab-frontend frontend
# nginx 가 /api 는 backend, /agent 는 agent 로 넘긴다 (개발 서버의 Vite proxy 와 같은 구성).

FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /src/dist /usr/share/nginx/html
ENV BACKEND_URL=http://backend:4000 AGENT_URL=http://agent:8000
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD wget -qO- http://127.0.0.1/ > /dev/null || exit 1
