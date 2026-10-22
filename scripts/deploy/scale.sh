#!/usr/bin/env bash
# Switch the backends between demo mode and saving-credit mode.
#
#   ./scripts/deploy/scale.sh up     # backends min 1: always warm, data kept
#                                    # until the next deploy or restart
#   ./scripts/deploy/scale.sh down   # backends min 0: no charge while idle;
#                                    # first request after idle wakes the app
#                                    # (a few seconds) and RESETS its database
#                                    # to seed data
#   ./scripts/deploy/scale.sh status
#
# Frontends are always min 0 (they hold no data), so they are not touched.
# max stays 1 throughout: each backend's SQLite copy lives in its replica.

source "$(dirname "${BASH_SOURCE[0]}")/config.sh"

BACKENDS=(joshua-backend maxwell-backend thomas-backend enerel-backend hyunwoo-backend lehoalong-backend)

case "${1:-}" in
  up)   min=1 ;;
  down) min=0 ;;
  status)
    az containerapp list -g "$RESOURCE_GROUP" \
      --query "[].{app:name, min:properties.template.scale.minReplicas, max:properties.template.scale.maxReplicas, state:properties.runningStatus}" \
      -o table
    exit 0 ;;
  *) echo "usage: $0 up|down|status" >&2; exit 2 ;;
esac

for app in "${BACKENDS[@]}"; do
  echo "$app -> min $min"
  az containerapp update -n "$app" -g "$RESOURCE_GROUP" --min-replicas "$min" --max-replicas 1 --only-show-errors -o none
done
