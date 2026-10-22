#!/usr/bin/env bash
# First-time (or full) deploy from a developer machine: infrastructure, then
# images, then apps. GitHub Actions runs only 02 and 03.
#
#   ./scripts/deploy/deploy-all.sh

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "$DIR/01-infra.sh"
bash "$DIR/02-build-images.sh"
bash "$DIR/03-deploy-apps.sh"
