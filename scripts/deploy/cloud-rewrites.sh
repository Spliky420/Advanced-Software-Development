#!/usr/bin/env bash
# CLOUD REWRITES -- the only changes made to anyone's code for Azure.
#
# Applied to a throwaway copy of the source (the build staging directory),
# never to the repository. Each rewrite swaps an address that only works under
# docker compose on a laptop for its Azure Container Apps equivalent. Nothing
# else in any file is touched.
#
# Why each is needed:
#   1. Shared home page links to http://localhost:80X0. In the cloud each
#      frontend has its own https URL.
#   2. Joshua, Enerel and LeHoaLong's nginx proxy /api to "<name>-backend:5000"
#      and forward the browser's Host header. In Container Apps an internal app
#      is reached at http://<name>-backend on port 80, and the environment
#      routes by Host header -- so the port is dropped and Host is set to the
#      backend's name (otherwise the request is routed back to the frontend).
#      nginx also proxies with HTTP/1.0 by default, which the Container Apps
#      ingress refuses (426 Upgrade Required), so HTTP/1.1 is switched on.
#   3. Maxwell's page calls http://localhost:8021 from the browser. Points it
#      at Maxwell's backend's public https URL instead.
#   4. HyunWoo's page calls <page host>:8041 from the browser. Container Apps
#      only serves 443, so it points at HyunWoo's backend's public URL instead.
#
# Every rewrite is checked: if a file no longer contains the expected text
# (because its owner changed it), the build stops rather than deploying a
# frontend that silently points at localhost.
#
# Usage: cloud-rewrites.sh <staging dir> <environment default domain>

set -euo pipefail
STAGE="$1"
DOMAIN="$2"

# Replace $2 with $3 in file $1, failing if $2 is not present before or is
# still present after.
rewrite() {
  local file="$STAGE/$1" from="$2" to="$3"
  grep -qF -- "$from" "$file" || { echo "cloud-rewrites: '$from' not found in $1" >&2; exit 1; }
  # Escape for sed: | is the delimiter, & and \ are special on the right side.
  local f t
  f="$(printf '%s' "$from" | sed 's/[][\.*^$|/]/\\&/g')"
  t="$(printf '%s' "$to" | sed 's/[|&\\]/\\&/g')"
  sed -i "s|$f|$t|g" "$file"
  ! grep -qF -- "$from" "$file" || { echo "cloud-rewrites: '$from' still in $1" >&2; exit 1; }
  echo "  $1: $from -> $to"
}

echo "Cloud rewrites (domain: $DOMAIN)"

# 1. Shared home page links -> each frontend's public URL.
rewrite shared/index.html "http://localhost:8010" "https://joshua-frontend.$DOMAIN"
rewrite shared/index.html "http://localhost:8020" "https://maxwell-frontend.$DOMAIN"
rewrite shared/index.html "http://localhost:8030" "https://enerel-frontend.$DOMAIN"
rewrite shared/index.html "http://localhost:8040" "https://hyunwoo-frontend.$DOMAIN"
rewrite shared/index.html "http://localhost:8050" "https://thomas-frontend.$DOMAIN"
rewrite shared/index.html "http://localhost:8060" "https://lehoalong-frontend.$DOMAIN"

# 2. nginx proxies -> internal Container Apps address, with a matching Host.
for name in joshua enerel lehoalong; do
  dir="$name"; [[ "$name" == enerel ]] && dir="Enerel"; [[ "$name" == lehoalong ]] && dir="LeHoaLong"
  rewrite "$dir/frontend/nginx.conf" "http://$name-backend:5000" "http://$name-backend"
  rewrite "$dir/frontend/nginx.conf" 'proxy_set_header Host $host;' "proxy_set_header Host $name-backend; proxy_http_version 1.1;"
done

# 3. Maxwell: browser -> backend's public URL.
rewrite Maxwell/frontend/index.html "http://localhost:8021" "https://maxwell-backend.$DOMAIN"

# 4. HyunWoo: browser -> backend's public URL.
rewrite hyunwoo/frontend/app.js \
  '${window.location.protocol}//${window.location.hostname}:8041/api' \
  "https://hyunwoo-backend.$DOMAIN/api"
