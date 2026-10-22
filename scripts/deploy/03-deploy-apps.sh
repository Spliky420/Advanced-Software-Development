#!/usr/bin/env bash
# Create or update one container app per service, using the images pushed by
# 02-build-images.sh.
#
# Layout: the 19 services in docker-compose.yml become 13 container apps (the
# 6 databases run inside their backend's app, see DATABASES below):
#
#   shared-frontend, <student>-frontend   external ingress (public https URL)
#   <student>-backend                     internal ingress only, reached by its
#                                         frontend at http://<student>-backend
#     except maxwell-backend and hyunwoo-backend: external, because those two
#     frontends call their backend from the browser (see cloud-rewrites.sh)
#
# DATABASES: every student's database is SQLite -- a file, not a server. Under
# compose the database container seeds the file on a shared volume and the
# backend opens it. Separate container apps cannot share a disk, so here the
# database image runs as an INIT CONTAINER inside its backend's app, seeding an
# EmptyDir volume that the backend then mounts at /data. Consequences:
#   - data resets to the seed data whenever the replica restarts;
#   - backends are pinned to exactly 1 replica (min 1 so a demo never hits a
#     reset from scale-to-zero, max 1 so there is only ever one copy of the
#     data). scale.sh lowers min to 0 when not demoing, to save credit.
# The database images end in `tail -f /dev/null` to keep a compose container
# alive; an init container must exit, so that one line is dropped at start.
#
#   ./scripts/deploy/03-deploy-apps.sh            # uses the tag 02 just pushed
#   IMAGE_TAG=<tag> ./scripts/deploy/03-deploy-apps.sh

_explicit_tag="${IMAGE_TAG:-}"
source "$(dirname "${BASH_SOURCE[0]}")/config.sh"
if [[ -n "$_explicit_tag" ]]; then
  IMAGE_TAG="$_explicit_tag"
elif [[ -f "$DEPLOY_DIR/.last-image-tag" ]]; then
  IMAGE_TAG="$(cat "$DEPLOY_DIR/.last-image-tag")"
else
  echo "No image tag: run 02-build-images.sh first or set IMAGE_TAG." >&2; exit 1
fi

ENV_ID="$(azq containerapp env show -n "$ACA_ENV" -g "$RESOURCE_GROUP" --query id -o tsv)"
PULL_ID="$(azq identity show -n "$PULL_IDENTITY" -g "$RESOURCE_GROUP" --query id -o tsv)"
YAML_DIR="$(mktemp -d)"
trap 'rm -rf "$YAML_DIR"' EXIT

# Empty AI service URLs: no Ollama, MCP or RAG server exists in the cloud.
NO_AI=( "AI_MODE_ENABLED=$AI_MODE_ENABLED" "OLLAMA_BASE_URL=" "MCP_SERVER_URL=" "RAG_SERVER_URL=" )

# env_yaml INDENT KEY=VALUE... -> a YAML env list
env_yaml() {
  local pad; pad="$(printf '%*s' "$1" '')"; shift
  if [[ $# -eq 0 ]]; then echo "${pad}[]"; return; fi
  local kv
  for kv in "$@"; do
    printf '%s- name: %s\n%s  value: "%s"\n' "$pad" "${kv%%=*}" "$pad" "${kv#*=}"
  done
}

# deploy NAME PORT external|internal MIN MAX [--db DB_IMAGE ENTRYPOINT DBENV...] -- ENV...
deploy() {
  local name="$1" port="$2" ingress="$3" min="$4" max="$5"; shift 5
  local db_image="" db_entry="" db_env=() app_env=()
  if [[ "${1:-}" == --db ]]; then
    db_image="$2" db_entry="$3"; shift 3
    while [[ $# -gt 0 && "$1" != -- ]]; do db_env+=("$1"); shift; done
  fi
  [[ "${1:-}" == -- ]] && shift
  app_env=("$@")

  local external=false insecure=true
  if [[ "$ingress" == external ]]; then external=true; insecure=false; fi

  local file="$YAML_DIR/$name.yaml"
  {
    cat <<EOF
location: $LOCATION
identity:
  type: UserAssigned
  userAssignedIdentities:
    $PULL_ID: {}
properties:
  managedEnvironmentId: $ENV_ID
  configuration:
    activeRevisionsMode: Single
    ingress:
      external: $external
      targetPort: $port
      transport: auto
      allowInsecure: $insecure
    registries:
      - server: $ACR_SERVER
        identity: $PULL_ID
  template:
EOF
    if [[ -n "$db_image" ]]; then
      cat <<EOF
    initContainers:
      - name: database
        image: $ACR_SERVER/$db_image:$IMAGE_TAG
        command: ["/bin/sh", "-c"]
        args:
          - "grep -v 'tail -f /dev/null' $db_entry > /tmp/seed.sh && exec sh /tmp/seed.sh"
        resources:
          cpu: $CPU
          memory: $MEMORY
        env:
$(env_yaml 10 "${db_env[@]}")
        volumeMounts:
          - volumeName: data
            mountPath: /data
EOF
    fi
    cat <<EOF
    containers:
      - name: $name
        image: $ACR_SERVER/$name:$IMAGE_TAG
        resources:
          cpu: $CPU
          memory: $MEMORY
        env:
$(env_yaml 10 "${app_env[@]}")
EOF
    if [[ -n "$db_image" ]]; then
      cat <<EOF
        volumeMounts:
          - volumeName: data
            mountPath: /data
EOF
    fi
    cat <<EOF
    scale:
      minReplicas: $min
      maxReplicas: $max
EOF
    if [[ -n "$db_image" ]]; then
      cat <<EOF
    volumes:
      - name: data
        storageType: EmptyDir
EOF
    fi
  } > "$file"

  echo
  echo "--- $name ($ingress, port $port, replicas $min-$max${db_image:+, db init: $db_image})"
  # Always `create`: with --yaml it is a full PUT, so it also updates an
  # existing app. (`az containerapp update --yaml` fails on some apps with a
  # bogus IdentityDoesNotExist error for the user-assigned identity.)
  local attempt
  for attempt in 1 2 3; do
    if az containerapp create -n "$name" -g "$RESOURCE_GROUP" --yaml "$(native_path "$file")" --only-show-errors -o none; then
      return 0
    fi
    echo "  deploy failed (attempt $attempt/3), retrying in 20s..." >&2; sleep 20
  done
  return 1
}

log "Deploying apps with tag $IMAGE_TAG"

# --- Backends first: the nginx frontends resolve their backend at start. ---

deploy joshua-backend 5000 internal 1 1 \
  --db joshua-database /usr/local/bin/entrypoint.sh "DB_FILE=/data/portfolio.db" -- \
  "DB_PATH=/data/portfolio.db" "OLLAMA_MODEL=qwen2.5:0.5b" "DRIFT_THRESHOLD_PERCENT=5" "${NO_AI[@]}"

deploy maxwell-backend 5000 external 1 1 \
  --db maxwell-database /usr/local/bin/entrypoint.sh "DB_FILE=/data/glossary.sqlite" -- \
  "DATABASE=/data/glossary.sqlite" "OLLAMA_MODEL=qwen2.5:0.5b" \
  "DISABLE_AI_MODE=true" "DISABLE_MCP_PROXY=true" "DISABLE_RAG_PROXY=true" "${NO_AI[@]}"

deploy thomas-backend 5001 internal 1 1 \
  --db thomas-database /app/entrypoint.sh "DB_FILE=/data/transactions.db" -- \
  "DATABASE_PATH=/data/transactions.db" "OLLAMA_URL=" "OLLAMA_MODEL=qwen2.5:0.5b" \
  "MULTI_AGENT_URL=" "${NO_AI[@]}"

deploy enerel-backend 5000 internal 1 1 \
  --db enerel-database /usr/local/bin/entrypoint.sh "DB_FILE=/data/library.db" -- \
  "DB_PATH=/data/library.db" "OLLAMA_MODEL=qwen2.5:0.5b" "OLLAMA_EMBED_MODEL=nomic-embed-text" \
  "MCP_ENABLED=false" "RAG_ENABLED=false" "${NO_AI[@]}"

deploy hyunwoo-backend 5000 external 1 1 \
  --db hyunwoo-database /entrypoint.sh "DB_FILE=/data/bills.db" -- \
  "DB_PATH=/data/bills.db" "OLLAMA_MODEL=qwen2.5:0.5b" \
  "MCP_ENABLED=false" "RAG_ENABLED=false" "${NO_AI[@]}"

deploy lehoalong-backend 5000 internal 1 1 \
  --db lehoalong-database /usr/local/bin/entrypoint.sh "DB_FILE=/data/goals.db" "INIT_DB_FORCE=0" -- \
  "DB_PATH=/data/goals.db" "OLLAMA_MODEL=qwen2.5:0.5b" \
  "MCP_ENABLED=false" "RAG_ENABLED=false" "MULTI_AGENT_ENABLED=false" "MULTI_AGENT_URL=" "${NO_AI[@]}"

# --- Frontends: public, scale to zero when idle. ---

deploy joshua-frontend    80   external 0 1 --
deploy maxwell-frontend   80   external 0 1 --
deploy thomas-frontend    5000 external 0 1 -- "BACKEND_URL=http://thomas-backend"
deploy enerel-frontend    80   external 0 1 --
deploy hyunwoo-frontend   80   external 0 1 --
deploy lehoalong-frontend 80   external 0 1 --
deploy shared-frontend    80   external 0 1 --

DOMAIN="$(env_domain)"
log "Deployed. Public URLs:"
echo "  Home page  https://shared-frontend.$DOMAIN"
for s in joshua maxwell thomas enerel hyunwoo lehoalong; do
  printf '  %-10s https://%s-frontend.%s\n' "$s" "$s" "$DOMAIN"
done
