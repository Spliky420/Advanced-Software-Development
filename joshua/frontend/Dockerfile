# Joshua's frontend microservice -- React (Vite) built to static assets and
# served by nginx.
#
# Two stages so Node and the dependency tree never reach the runtime image:
# the final image is nginx plus the contents of dist/, nothing else.

# ---------------------------------------------------------------------------
# Stage 1 -- build the static assets.
# ---------------------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

# Copy the manifests first so `npm ci` is only re-run when dependencies
# actually change, not on every source edit.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 -- serve them.
# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
