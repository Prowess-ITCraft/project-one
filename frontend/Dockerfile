# syntax=docker/dockerfile:1.7
FROM node:22.13-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22.13-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
ARG API_ORIGIN=http://api:9596
ENV API_ORIGIN=$API_ORIGIN
RUN npm run build

FROM node:22.13-alpine AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=9595 HOSTNAME=0.0.0.0
WORKDIR /app
RUN addgroup -S -g 10001 p1 && adduser -S -u 10001 -G p1 p1
COPY --from=build --chown=p1:p1 /app/.next/standalone ./
COPY --from=build --chown=p1:p1 /app/.next/static ./.next/static
# Logos and other files served as they are (Next standalone does not include public/).
COPY --from=build --chown=p1:p1 /app/public ./public
USER p1
EXPOSE 9595
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD wget -qO- http://127.0.0.1:9595/login >/dev/null || exit 1
CMD ["node", "server.js"]
