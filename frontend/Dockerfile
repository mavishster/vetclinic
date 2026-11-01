# Интерфейс для сервера клиники: собираем один раз, отдаёт nginx.
# nginx же — единая точка входа: /api и /admin уходят в backend, остальное — интерфейс.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
