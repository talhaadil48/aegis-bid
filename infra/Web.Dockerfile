FROM node:20-alpine AS build
WORKDIR /app
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web ./
RUN npm run build
FROM nginx:1.27-alpine
COPY --from=build /app/out /usr/share/nginx/html
COPY infra/nginx.conf /etc/nginx/nginx.conf
