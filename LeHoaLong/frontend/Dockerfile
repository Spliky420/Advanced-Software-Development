# Le Hoa Long's frontend microservice -- React (Vite) built to static assets
# and served by nginx on port 80 (published as 8060).
#
# BUILD CONTEXT IS THE REPOSITORY ROOT, not this directory, because the app
# imports the team's shared stylesheet from shared/styles.css. The build stage
# reproduces the repo's own layout so the one relative import path in
# src/styles/app.css resolves identically here and under `npm run dev`.
#
#   docker build -f LeHoaLong/frontend/Dockerfile .
#
# Two stages so Node and node_modules never reach the runtime image: the final
# image is nginx plus the contents of dist/, nothing else.

# ---------------------------------------------------------------------------
# Stage 1 -- build the static assets.
# ---------------------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /build

# Manifests first, so `npm ci` is only re-run when dependencies actually
# change rather than on every source edit.
COPY LeHoaLong/frontend/package.json LeHoaLong/frontend/package-lock.json ./LeHoaLong/frontend/
WORKDIR /build/LeHoaLong/frontend
RUN npm ci

# The shared theme, at the same relative position it occupies in the repo.
COPY shared/styles.css /build/shared/styles.css
COPY LeHoaLong/frontend/ /build/LeHoaLong/frontend/

RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 -- serve them.
# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine

COPY LeHoaLong/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/LeHoaLong/frontend/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD wget --quiet --spider http://127.0.0.1/ || exit 1
