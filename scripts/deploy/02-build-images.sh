#!/usr/bin/env bash
# Build every service image from committed source and push it to ACR.
#
#   1. Export MAIN_REF (default HEAD) into a temporary staging directory with
#      `git archive` -- committed files only, no local node_modules, .env or
#      databases.
#   2. Apply cloud-rewrites.sh to the staging copy (needs the environment's
#      domain, so 01-infra.sh must have run).
#   3. Build and push each image as $ACR_SERVER/<service>:$IMAGE_TAG.
#
# BUILD_MODE: docker (local Docker daemon, also what GitHub Actions uses),
#             acr    (az acr build -- builds inside Azure, no Docker needed;
#                     NOT available on Azure for Students, which rejects it
#                     with TasksOperationsNotAllowed),
#             auto   (default: docker if a daemon is reachable, else acr).
#
#   ./scripts/deploy/02-build-images.sh
# Writes the tag it used to $DEPLOY_DIR/.last-image-tag for 03-deploy-apps.sh.

source "$(dirname "${BASH_SOURCE[0]}")/config.sh"

BUILD_MODE="${BUILD_MODE:-auto}"
if [[ "$BUILD_MODE" == auto ]]; then
  if docker info >/dev/null 2>&1; then BUILD_MODE=docker; else BUILD_MODE=acr; fi
fi

DOMAIN="$(env_domain)"
[[ -n "$DOMAIN" ]] || { echo "No Container Apps environment found -- run 01-infra.sh first." >&2; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

log "Staging $MAIN_REF ($(git -C "$REPO_ROOT" rev-parse --short "$MAIN_REF")) into $STAGE"
git -C "$REPO_ROOT" archive --format=tar "$MAIN_REF" | tar -x -C "$STAGE"

log "Applying cloud rewrites"
bash "$DEPLOY_DIR/cloud-rewrites.sh" "$STAGE" "$DOMAIN"

log "Building ${#SERVICES[@]} images with $BUILD_MODE, tag $IMAGE_TAG"
if [[ "$BUILD_MODE" == docker ]]; then
  az acr login -n "$ACR_NAME" --only-show-errors
fi

for entry in "${SERVICES[@]}"; do
  IFS='|' read -r name context dockerfile <<<"$entry"
  image="$ACR_SERVER/$name:$IMAGE_TAG"
  echo
  echo "--- $name ($context/$dockerfile)"
  if [[ "$BUILD_MODE" == docker ]]; then
    docker build --platform linux/amd64 -t "$image" \
      -f "$(native_path "$STAGE/$context/$dockerfile")" "$(native_path "$STAGE/$context")"
    docker push "$image"
  else
    # az acr build uploads the context and builds in Azure.
    az acr build -r "$ACR_NAME" -t "$name:$IMAGE_TAG" --platform linux/amd64 \
      -f "$(native_path "$STAGE/$context/$dockerfile")" "$(native_path "$STAGE/$context")" \
      --only-show-errors --no-logs -o none
  fi
done

echo "$IMAGE_TAG" > "$DEPLOY_DIR/.last-image-tag"
log "Pushed all images with tag $IMAGE_TAG"
