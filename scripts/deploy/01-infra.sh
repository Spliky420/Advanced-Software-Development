#!/usr/bin/env bash
# One-off infrastructure: resource group, registry, Container Apps environment,
# and the two managed identities (GitHub OIDC login + image pull).
#
# Safe to re-run: every step checks before creating. Run from a machine logged
# in as a subscription Owner (role assignments need it). GitHub Actions does
# NOT run this script -- its identity is deliberately not allowed to.
#
#   ./scripts/deploy/01-infra.sh

source "$(dirname "${BASH_SOURCE[0]}")/config.sh"

SUBSCRIPTION_ID="$(azq account show --query id -o tsv)"
TENANT_ID="$(azq account show --query tenantId -o tsv)"

log "Resource providers"
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.ContainerRegistry Microsoft.ManagedIdentity; do
  az provider register -n "$ns" --wait --only-show-errors
  echo "  $ns: $(azq provider show -n "$ns" --query registrationState -o tsv)"
done

log "Resource group $RESOURCE_GROUP ($LOCATION)"
az group create -n "$RESOURCE_GROUP" -l "$LOCATION" --only-show-errors -o none
RG_ID="$(azq group show -n "$RESOURCE_GROUP" --query id -o tsv)"

log "Container registry $ACR_NAME (Basic, admin user disabled)"
if ! az acr show -n "$ACR_NAME" -g "$RESOURCE_GROUP" -o none 2>/dev/null; then
  az acr create -n "$ACR_NAME" -g "$RESOURCE_GROUP" -l "$LOCATION" \
    --sku Basic --admin-enabled false --only-show-errors -o none
fi
ACR_ID="$(azq acr show -n "$ACR_NAME" -g "$RESOURCE_GROUP" --query id -o tsv)"

log "Log Analytics workspace $LOG_WORKSPACE (30-day retention)"
if ! az monitor log-analytics workspace show -n "$LOG_WORKSPACE" -g "$RESOURCE_GROUP" -o none 2>/dev/null; then
  az monitor log-analytics workspace create -n "$LOG_WORKSPACE" -g "$RESOURCE_GROUP" \
    -l "$LOCATION" --retention-time 30 --only-show-errors -o none
fi
LOG_CUSTOMER_ID="$(azq monitor log-analytics workspace show -n "$LOG_WORKSPACE" -g "$RESOURCE_GROUP" --query customerId -o tsv)"

log "Container Apps environment $ACA_ENV (workload profiles, Consumption profile)"
# Created through the ARM API, not `az containerapp env create`: on this
# subscription the CLI creates an *Express* environment, which rejects init
# containers, plain-HTTP internal ingress and app-name service discovery --
# all three of which this deployment relies on. environmentMode is set
# explicitly instead (a preview API version: the GA one has no such field).
# The Consumption profile is pay-per-use, like Express.
ENV_URL="https://management.azure.com${RG_ID}/providers/Microsoft.App/managedEnvironments/${ACA_ENV}?api-version=2025-10-02-preview"
if ! az containerapp env show -n "$ACA_ENV" -g "$RESOURCE_GROUP" -o none 2>/dev/null; then
  # The body carries the Log Analytics shared key, so it goes through a
  # private temp file that is deleted straight after; it is never printed.
  body="$(mktemp)"; chmod 600 "$body"
  cat > "$body" <<EOF
{
  "location": "$LOCATION",
  "properties": {
    "environmentMode": "WorkloadProfiles",
    "workloadProfiles": [ { "name": "Consumption", "workloadProfileType": "Consumption" } ],
    "appLogsConfiguration": {
      "destination": "log-analytics",
      "logAnalyticsConfiguration": {
        "customerId": "$LOG_CUSTOMER_ID",
        "sharedKey": "$(azq monitor log-analytics workspace get-shared-keys -n "$LOG_WORKSPACE" -g "$RESOURCE_GROUP" --query primarySharedKey -o tsv)"
      }
    }
  }
}
EOF
  trap 'rm -f "$body"' EXIT
  az rest --method put --url "$ENV_URL" --body "@$(native_path "$body")" -o none
  rm -f "$body"
  echo "  waiting for provisioning (a workload profiles environment takes 10-20 min)..."
  while :; do
    state="$(azq rest --method get --url "$ENV_URL" --query properties.provisioningState -o tsv)"
    [[ "$state" == Succeeded ]] && break
    [[ "$state" == Failed || "$state" == Canceled ]] && { echo "  provisioning $state" >&2; exit 1; }
    sleep 20
  done
fi
mode="$(azq rest --method get --url "$ENV_URL" --query properties.environmentMode -o tsv)"
echo "  environmentMode: $mode"
if [[ "$mode" == Express ]]; then
  echo "  $ACA_ENV is an Express environment, which this deployment cannot use." >&2
  echo "  Delete it (az containerapp env delete -n $ACA_ENV -g $RESOURCE_GROUP) and re-run." >&2
  exit 1
fi

log "Managed identities"
for id in "$GITHUB_IDENTITY" "$PULL_IDENTITY"; do
  if ! az identity show -n "$id" -g "$RESOURCE_GROUP" -o none 2>/dev/null; then
    az identity create -n "$id" -g "$RESOURCE_GROUP" -l "$LOCATION" --only-show-errors -o none
  fi
  echo "  $id"
done
GH_PRINCIPAL="$(azq identity show -n "$GITHUB_IDENTITY" -g "$RESOURCE_GROUP" --query principalId -o tsv)"
GH_CLIENT_ID="$(azq identity show -n "$GITHUB_IDENTITY" -g "$RESOURCE_GROUP" --query clientId -o tsv)"
PULL_PRINCIPAL="$(azq identity show -n "$PULL_IDENTITY" -g "$RESOURCE_GROUP" --query principalId -o tsv)"

# A user-assigned managed identity with a federated credential replaces an app
# registration / service principal, which the UTS directory does not allow
# students to create. GitHub presents an OIDC token whose subject must match.
log "Federated credentials for $GITHUB_REPO"
for branch in $GITHUB_BRANCHES; do
  fc_name="github-${branch//[^A-Za-z0-9-]/-}"
  if ! az identity federated-credential show -n "$fc_name" --identity-name "$GITHUB_IDENTITY" -g "$RESOURCE_GROUP" -o none 2>/dev/null; then
    az identity federated-credential create -n "$fc_name" \
      --identity-name "$GITHUB_IDENTITY" -g "$RESOURCE_GROUP" \
      --issuer "https://token.actions.githubusercontent.com" \
      --subject "repo:${GITHUB_REPO}:ref:refs/heads/${branch}" \
      --audiences "api://AzureADTokenExchange" --only-show-errors -o none
  fi
  echo "  $fc_name -> repo:${GITHUB_REPO}:ref:refs/heads/${branch}"
done

# New identities can take a minute to become visible to role assignment;
# retry rather than fail on the first attempt.
assign_role() {  # principal role scope
  local n
  if [[ -n "$(azq role assignment list --assignee "$1" --role "$2" --scope "$3" --query '[0].id' -o tsv)" ]]; then
    echo "  $2 already assigned"; return
  fi
  for n in 1 2 3 4 5 6; do
    if az role assignment create --assignee-object-id "$1" --assignee-principal-type ServicePrincipal \
         --role "$2" --scope "$3" --only-show-errors -o none 2>/dev/null; then
      echo "  $2 assigned"; return
    fi
    echo "  waiting for identity to propagate ($n/6)..."; sleep 15
  done
  echo "  FAILED to assign $2 on $3" >&2; return 1
}

log "Role assignments (scoped to this resource group / registry only)"
assign_role "$GH_PRINCIPAL" "Contributor" "$RG_ID"
assign_role "$PULL_PRINCIPAL" "AcrPull" "$ACR_ID"

log "Done. GitHub repository variables for cloud-deployment.yml (IDs, not secrets):"
echo "  AZURE_CLIENT_ID       = $GH_CLIENT_ID"
echo "  AZURE_TENANT_ID       = $TENANT_ID"
echo "  AZURE_SUBSCRIPTION_ID = $SUBSCRIPTION_ID"
echo "  Environment domain    = $(env_domain)"
