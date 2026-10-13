# Managed local deployment

This module builds the Meridian application image and manages a hardened Docker deployment: a dedicated bridge network, one non-root container and a persistent journal volume. It provisions local Docker resources; it does not create cloud accounts or remote services.

## Prerequisites

Use the pinned Terraform version in `.terraform-version`, a running local Docker Engine with the Docker CLI and Buildx plugin, and a checkout of this repository. Provider `kreuzwerker/docker` is pinned and its checksums are recorded in `.terraform.lock.hcl`.

## Deploy

```bash
cd infra/terraform
export TF_VAR_api_token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export TF_VAR_docker_host="unix:///var/run/docker.sock"
# Colima users may set the profile's Unix socket, for example:
# export TF_VAR_docker_host="unix://$HOME/.colima/default/docker.sock"
export DOCKER_HOST="$TF_VAR_docker_host"
terraform init -input=false -lockfile=readonly
terraform plan -out=deployment.tfplan
terraform apply deployment.tfplan
terraform output console_url
```

Supply `TF_VAR_host_port` to choose another loopback port, and `TF_VAR_name` for an independent dataset. The defaults are `meridian` and port `8080`. `DOCKER_HOST` keeps the Buildx image builder on the same daemon as the Terraform provider without changing your saved Docker context. Export the same token as `MERIDIAN_API_TOKEN` in a shell used by HTTP clients; enter it through the console connection panel for browser requests.

Apply builds from the checked-out Dockerfile and waits for the application's authenticated readiness probe. A hash of the actual build inputs triggers image/container replacement when source changes. The journal volume stays separate from container lifetime.

## Inputs and outputs

| Input | Default | Validation |
| --- | --- | --- |
| `docker_host` | `unix:///var/run/docker.sock` | Local Unix socket |
| `name` | `meridian` | 3–40 lowercase name characters |
| `host_port` | `8080` | Integer 1024–65535, loopback bind |
| `api_token` | Required | At least 32 printable ASCII characters, no whitespace |
| `memory_mb` | `256` | Integer 128–4096 |

Outputs include the console URL, container name, persistent volume and source digest. No token is exposed as an output.

## Security and state

The container runs as UID/GID 10001, drops all Linux capabilities, blocks privilege escalation, limits memory/log storage, and has a read-only root filesystem. Only `/data` and a bounded `/tmp` tmpfs are writable. HTTP is published on loopback; remote use requires a separately managed TLS proxy and trusted network configuration.

The service uses a standard bridge to support loopback port publication. It can make outbound connections. Docker's `internal` network mode removes external connectivity and does not suit this host-accessible console; see the [Docker networking reference](https://docs.docker.com/compose/how-tos/networking/#internal-networks). This module does not enforce an outbound firewall policy.

Terraform state and saved plans contain the bearer token despite its sensitive display setting. Keep those files private, never commit them, and use an access-controlled encrypted backend for shared operation. The repository ignores state, plan files and real `.tfvars`; `.dockerignore` also excludes them from image build context.

The journal volume has `prevent_destroy = true`. An ordinary `terraform destroy` therefore refuses to remove business records. For a container refresh, apply source changes normally. For decommissioning, first export and verify a backup through the operations runbook; detach the protected volume from Terraform state only when retention/deletion is an explicit operator decision.

Do not edit or migrate an active journal by copying arbitrary files into its volume. Use the application's verified backup/restore tools.

## Validate without creating resources

```bash
terraform fmt -check -recursive
terraform init -backend=false -input=false -lockfile=readonly
terraform validate
terraform test
```

Tests use a mocked Docker provider and plan-only runs. They verify security settings, instance isolation, outputs and rejected token/socket/port/name/memory inputs. CI also exercises a separate synthetic deployment on its own Docker daemon, verifies authenticated readiness and journal persistence after restart, then removes only those test resources.

Run the same live check from the repository root with `python3 tools/deploy_smoke.py`. For a separate local Docker profile, supply `--docker-host unix:///absolute/path/to/docker.sock`. The check uses a temporary checkout, state directory, randomly named resources and synthetic records; its summary is written to `build/test-results/terraform-smoke.json` without tokens or state.
