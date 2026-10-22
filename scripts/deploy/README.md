# Azure Container Apps deployment

Bash + Azure CLI scripts that deploy the whole stack to Azure Container Apps.
Run them from Git Bash or Linux, logged in with `az login`.

| Script | What it does | Who runs it |
|---|---|---|
| `config.sh` | Names, region, sizes, service list. Every value can be overridden with an env var. | sourced by the others |
| `01-infra.sh` | Resource group, Basic ACR, Log Analytics, Container Apps environment, managed identities, GitHub federated credentials, role assignments | a subscription Owner, once |
| `02-build-images.sh` | Copies committed source to a temp dir, applies `cloud-rewrites.sh`, builds and pushes 19 images | developer machine or GitHub Actions |
| `cloud-rewrites.sh` | Swaps the few `localhost` / compose-only addresses for their cloud equivalents in the temp copy. The repo is never changed. | called by 02 |
| `03-deploy-apps.sh` | Creates or updates the 13 container apps | developer machine or GitHub Actions |
| `scale.sh up\|down\|status` | Keeps backends warm for a demo (`up`) or lets them scale to zero to save credit (`down`) | anyone with access |
| `deploy-all.sh` | 01, then 02, then 03 | first deploy |

## What is public

- External (https): `shared-frontend` (home page) and every `<student>-frontend`.
  `maxwell-backend` and `hyunwoo-backend` are also external, because those
  frontends call their backend straight from the browser.
- Internal only: the other backends, reached by their frontend at `http://<student>-backend`.
- Databases (SQLite): not separate apps. Each runs as an init container in its
  backend's app and seeds a disk local to that replica. **Data resets to the
  seed data when a backend restarts.**

AI is off in the cloud. Every backend gets `AI_MODE_ENABLED=false` and empty
Ollama / MCP / RAG URLs, because none of those servers is deployed.

## Temporary override

Until Joshua's Release 2 PR is merged, `joshua/` is built from
`origin/Joshua-Release-1` (see `JOSHUA_REF` in `config.sh` and
`02-build-images.sh`). Remove that block once the PR is merged.

## Secrets

None. GitHub Actions logs in with OIDC as a user-assigned managed identity,
with no client secret. The apps pull images with a second managed identity,
with no registry password.
