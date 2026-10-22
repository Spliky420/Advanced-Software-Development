#!/usr/bin/env bash
# Shared settings for every script in scripts/deploy/. Sourced, not run.
#
# Every value can be overridden from the environment, e.g.
#   LOCATION=japaneast RESOURCE_GROUP=rg-test ./scripts/deploy/deploy-all.sh
#
# Nothing in here is a secret. GitHub Actions logs in with OIDC (no client
# secret anywhere) and the container apps pull images with a managed identity
# (no registry password anywhere).

set -euo pipefail

# Git Bash on Windows rewrites arguments that look like POSIX paths, which
# mangles Azure resource IDs ("/subscriptions/..."). No effect on Linux.
export MSYS_NO_PATHCONV=1

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$DEPLOY_DIR/../.." && pwd)"
# ...which also stops Windows git/az/docker understanding /c/... paths, so
# hand them C:/... instead.
if command -v cygpath >/dev/null 2>&1; then
  DEPLOY_DIR="$(cygpath -m "$DEPLOY_DIR")"
  REPO_ROOT="$(cygpath -m "$REPO_ROOT")"
fi

# --- Azure -----------------------------------------------------------------
# Azure for Students only allows a handful of regions (policy "Allowed
# resource deployment regions"); australiaeast is one of them. List yours with:
#   az policy assignment list --query "[].parameters.listOfAllowedLocations"
LOCATION="${LOCATION:-australiaeast}"
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-asd2026}"
LOG_WORKSPACE="${LOG_WORKSPACE:-log-asd2026}"
ACA_ENV="${ACA_ENV:-cae-asd2026}"

# ACR names are globally unique, lowercase alphanumeric. Default: a fixed
# prefix plus the first 6 characters of the subscription ID, so it is stable
# for one subscription and unlikely to collide with anyone else's.
if [[ -z "${ACR_NAME:-}" ]]; then
  _sub="$(az account show --query id -o tsv | tr -d '\r-')"
  ACR_NAME="asd2026${_sub:0:6}"
fi
ACR_SERVER="${ACR_NAME}.azurecr.io"

# Two identities, so each has only what it needs:
#   GITHUB_IDENTITY  - GitHub Actions logs in as this (OIDC). Contributor on
#                      the resource group only: push images, update apps.
#   PULL_IDENTITY    - attached to every container app. AcrPull on the
#                      registry only, so app code never holds deploy rights.
GITHUB_IDENTITY="${GITHUB_IDENTITY:-id-asd2026-github}"
PULL_IDENTITY="${PULL_IDENTITY:-id-asd2026-acrpull}"

# --- GitHub (federated credential subjects) ---------------------------------
GITHUB_REPO="${GITHUB_REPO:-Spliky420/Advanced-Software-Development}"
# One federated credential per branch allowed to deploy. main is where the
# workflow runs after merge; cloud-deployment lets the PR branch be tested
# with a manual run before merge.
GITHUB_BRANCHES="${GITHUB_BRANCHES:-main cloud-deployment}"

# --- Source -----------------------------------------------------------------
# What to build. MAIN_REF is the base for every service.
MAIN_REF="${MAIN_REF:-HEAD}"

# Image tag: commit SHA in CI, otherwise a timestamp plus the local commit.
IMAGE_TAG="${IMAGE_TAG:-$(date -u +%Y%m%d%H%M%S)-$(git -C "$REPO_ROOT" rev-parse --short "$MAIN_REF")}"

# --- Sizing (consumption plan, smallest valid sizes) ------------------------
CPU="${CPU:-0.25}"
MEMORY="${MEMORY:-0.5Gi}"

# --- AI ---------------------------------------------------------------------
# Off in the cloud: there is no Ollama, MCP or RAG server deployed. Each
# backend gets AI_MODE_ENABLED=false (plus its own equivalent switch, where it
# has one) and empty AI service URLs. See 03-deploy-apps.sh.
AI_MODE_ENABLED="${AI_MODE_ENABLED:-false}"

# --- Services -----------------------------------------------------------------
# name | build context (repo-relative) | Dockerfile (relative to context)
# Mirrors the build: entries in docker-compose.yml.
SERVICES=(
  "shared-frontend|shared|Dockerfile"
  "joshua-database|joshua/database|Dockerfile"
  "joshua-backend|joshua/backend|Dockerfile"
  "joshua-frontend|joshua/frontend|Dockerfile"
  "maxwell-database|Maxwell/database|Dockerfile"
  "maxwell-backend|Maxwell/backend|Dockerfile"
  "maxwell-frontend|.|Maxwell/frontend/Dockerfile"
  "thomas-database|Thomas/database|Dockerfile"
  "thomas-backend|Thomas/backend|Dockerfile"
  "thomas-frontend|Thomas/frontend|Dockerfile"
  "enerel-database|Enerel/database|Dockerfile"
  "enerel-backend|Enerel/backend|Dockerfile"
  "enerel-frontend|Enerel/frontend|Dockerfile"
  "hyunwoo-database|hyunwoo/database|Dockerfile"
  "hyunwoo-backend|hyunwoo/backend|Dockerfile"
  "hyunwoo-frontend|hyunwoo/frontend|Dockerfile"
  "lehoalong-database|LeHoaLong/database|Dockerfile"
  "lehoalong-backend|LeHoaLong/backend|Dockerfile"
  "lehoalong-frontend|.|LeHoaLong/frontend/Dockerfile"
)

# --- Helpers ----------------------------------------------------------------
log() { printf '\n==> %s\n' "$*"; }

# az output on Windows can carry \r; strip it so values compare cleanly.
azq() { az "$@" | tr -d '\r'; }

# Windows builds of az/docker need Windows paths for files; no-op elsewhere.
native_path() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi
}

env_domain() {
  azq containerapp env show -n "$ACA_ENV" -g "$RESOURCE_GROUP" --query properties.defaultDomain -o tsv
}
