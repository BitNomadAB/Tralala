FROM node:22-alpine AS build

RUN corepack enable
WORKDIR /app

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

# Caddy serves the SPA and proxies the API and worker surface. TLS is configuration rather than a
# second container: TRALALA_SITE_ADDRESS decides between plain HTTP and automatic HTTPS.
FROM caddy:2-alpine

COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv

EXPOSE 80 443

# The admin API is bound to the container's loopback, so this answers "is the configuration loaded
# and serving" whichever scheme TRALALA_SITE_ADDRESS selected.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:2019/config/ || exit 1
