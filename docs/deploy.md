# Deploy and operate

For why the networking modes behave the way they do, read
[Networking](networking.md). For the trust model and the tradeoffs
behind these defaults, read [Security](security.md).

## Image and processes

One image serves everything — API, maintenance commands, migrations.
It's published to `ghcr.io/clawhaven/drukbox` on every release; build
`docker build -t ghcr.io/clawhaven/drukbox .` only to run a local change.

```bash
IMAGE=ghcr.io/clawhaven/drukbox:latest

# API (port 8780; /healthz for liveness probes)
docker run --rm -p 8780:8780 --env-file drukbox.env "$IMAGE"

# Migrations (one-off, before first start and on upgrades)
docker run --rm --env-file drukbox.env "$IMAGE" .venv/bin/alembic upgrade head

# Maintenance (cron, e.g. every 10-15 min)
docker run --rm --env-file drukbox.env "$IMAGE" .venv/bin/python -m hosts.janitor
docker run --rm --env-file drukbox.env "$IMAGE" .venv/bin/python -m hosts.pool
```

The janitor reaps expired and orphaned hosts. The pool maintainer
pre-provisions warm hosts and only does anything when `POOL_SIZE > 0`.
Schedule both under your cron infrastructure (k8s `CronJob`, systemd
timer) from the same image and env file.

Use Postgres in production (`postgresql+psycopg://...`). SQLite
(`sqlite+aiosqlite:///./drukbox.db`) is for single-process demos and
local development; the pool maintainer is safe under SQLite only with
a single runner.

The API binds all interfaces by default. When only loopback callers
reach it (host-networked, co-located client), set `UVICORN_HOST=127.0.0.1`
to keep the credential-holding control plane off other interfaces.

## Choose a provider

Three remote providers are supported and verified end to end: `exe`
(exe.dev), `aws` (EC2), and `hetzner` (Hetzner Cloud). A fourth, `docker`,
runs sandboxes as local containers and needs no external account — see
[Local sandboxes with Docker](#local-sandboxes-with-docker). `DEFAULT_HOST_PROVIDER`
selects which one serves `POST /hosts` (default `exe`). Set the matching
provider variables below. The image ships with all provider extras
installed.

## Local sandboxes with Docker

The `docker` provider runs each sandbox as a local container with sshd,
so you can try drukbox with no cloud account or API token. It needs a
Docker-compatible runtime on the host (Docker Desktop, OrbStack, Colima):

```bash
export DEFAULT_HOST_PROVIDER=docker
export TAILSCALE_ENABLED=false
```

The sandbox image (`DOCKER_DEFAULT_IMAGE`, default
`ghcr.io/clawhaven/drukbox/sandbox:latest`) is pulled on first provision.
To customize it, build [images/local/](../images/local/) and point
`DOCKER_DEFAULT_IMAGE` at your tag.

Containers publish sshd on a random `127.0.0.1` port and are reachable
only from the host that runs drukbox; the per-host key is the auth
boundary. Tailscale is not supported — a local container has no path
onto the tailnet, so `POST /hosts` fails fast if `TAILSCALE_ENABLED=true`.

This provider is for local development and demos, not production: it
talks to the host's Docker daemon, and granting drukbox access to that
socket is host-root-equivalent. Do not expose a docker-backed drukbox to
untrusted callers.

## Choose a networking mode

`TAILSCALE_ENABLED=false` (default): callers reach sandboxes over the
provider's public path. On AWS this means per-VM keypairs and the
managed security group — see
[Networking](networking.md#tailscale-off-public-path-key-only-auth).

`TAILSCALE_ENABLED=true`: sandboxes join your tailnet at boot and
callers connect over the overlay. Requires a Tailscale OAuth client
with auth-key write scope, and tailnet ACLs that (a) own the tags in
`TAILSCALE_AUTH_TAGS` and (b) permit tailscaled-SSH to the tagged
nodes.

## AWS credentials and IAM

AWS credentials come from the SDK's default chain (instance profile,
`~/.aws`, or env) — drukbox never plumbs them through its own
settings. The policy needs `ec2:RunInstances`,
`ec2:TerminateInstances`, `ec2:DescribeInstances`, `ec2:CreateTags`,
`sts:GetCallerIdentity`, plus — with Tailscale off —
`ec2:ImportKeyPair`, `ec2:DeleteKeyPair`, `ec2:CreateSecurityGroup`,
`ec2:DescribeSecurityGroups`, `ec2:AuthorizeSecurityGroupIngress`,
`ec2:DescribeSubnets` (when `AWS_SUBNET_ID` is set), and
`ssm:GetParameter` when `AWS_DEFAULT_IMAGE` is an SSM path.
Drukbox tags everything it creates with `managed-by=<SERVICE_LABEL>`,
so write permissions can be tag-scoped.

## Verify

```bash
curl -fsS -H "Authorization: Bearer $TOKEN" http://localhost:8780/doctor
```

`/doctor` runs one read-only probe per dependency (database, active
provider, Tailscale when enabled) and reports per-check status,
latency, and a remediation hint on failures. It always returns 200 —
health is the `ok` field. `GET /healthz` is the unauthenticated
liveness probe.

For a full end-to-end check, run the black-box suite against the
deployment (it provisions and destroys a real host — disposable
infrastructure only):

```bash
SERVICE_URL=http://localhost:8780 SERVICE_TOKEN=... npm --prefix api-tests test
```

## Configuration reference

Core, required:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Async SQLAlchemy URL. |
| `SERVICE_TOKENS` | Comma-separated bearer tokens accepted from trusted callers. |

Core, optional:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DEFAULT_HOST_PROVIDER` | `exe` | Provider used when callers don't specify one. |
| `SERVICE_LABEL` | `drukbox` | Label stamped onto provider resources (VM tags, SG tags). |
| `UVICORN_HOST` | `0.0.0.0` | API bind address. Set `127.0.0.1` to restrict to loopback. |
| `PROVISIONING_GRACE_SECONDS` | `600` | Safety TTL on in-flight hosts so the janitor reaps row + VM if the client disconnects mid-provision. Must exceed the worst-case provision duration. |
| `IDEMPOTENCY_KEY_TTL_HOURS` | `24` | Retention period for successful `Idempotency-Key` mappings. |
| `POOL_SIZE` | `0` | Warm hosts to keep ready. `0` disables pooling. |
| `POOL_HOST_MAX_AGE_HOURS` | `4` | Max age before the janitor reaps an unclaimed pool host. |
| `POOL_MAX_CREATES_PER_TICK` | `2` | Upper bound on pool provisions per tick; caps over-provision blast radius when ticks overlap. |

Tailscale (required when `TAILSCALE_ENABLED=true`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `TAILSCALE_ENABLED` | `false` | Provision hosts onto a tailnet. |
| `TAILSCALE_TAILNET` | — | Tailnet DNS suffix for sandbox MagicDNS hostnames. |
| `TAILSCALE_AUTH_TAGS` | — | Comma-separated tags applied to minted auth keys. |
| `TAILSCALE_OAUTH_CLIENT_ID` | — | OAuth client ID. |
| `TAILSCALE_OAUTH_CLIENT_SECRET` | — | OAuth client secret. |
| `TAILSCALE_API_TIMEOUT` | `30.0` | Timeout for Tailscale API calls. |
| `DEVICE_DISCOVERY_TIMEOUT_SECONDS` | `180.0` | How long provisioning waits for a sandbox to appear in the tailnet. |

exe.dev provider:

| Variable | Default | Purpose |
| --- | --- | --- |
| `EXE_API_TOKEN` | — (required) | Bearer token for the exe.dev exec API. |
| `EXE_DEFAULT_IMAGE` | — (required) | Image used when the caller omits `image`. |
| `EXE_API_URL` | `https://exe.dev` | API base URL. |
| `EXE_API_TIMEOUT` | `30.0` | Timeout for exe.dev API calls. |
| `EXE_BOOTSTRAP_SSH_TIMEOUT_SECONDS` | `30.0` | ssh-keyscan retry budget for a fresh exe.dev sandbox. |
| `EXE_SSH_USERNAME` | `exedev` | In-VM user callers SSH as. |

AWS provider:

| Variable | Default | Purpose |
| --- | --- | --- |
| `AWS_REGION` | — (required) | Region for the EC2 client and launches. |
| `AWS_DEFAULT_IMAGE` | — (required) | AMI id or SSM parameter path used when the caller omits `image`. |
| `AWS_INSTANCE_TYPE` | `t3.medium` | EC2 instance type. |
| `AWS_ROOT_GB` | `100` | Root EBS volume size (gp3, encrypted). |
| `AWS_SUBNET_ID` | — | Optional subnet; default VPC's otherwise. |
| `AWS_SECURITY_GROUP_ID` | — | Pre-existing SG; unset → drukbox manages `drukbox-managed`. |
| `AWS_SSH_CIDRS` | — | SSH ingress CIDRs. Authoritative when set; unset → detected egress `/32`, falling back to `0.0.0.0/0`. |
| `AWS_INSTANCE_PROFILE` | — | Optional IAM instance profile attached to sandboxes. |
| `AWS_BOOTSTRAP_SSH_TIMEOUT_SECONDS` | `120.0` | ssh-keyscan retry budget for a fresh EC2 instance. |
| `AWS_SSH_USERNAME` | `ubuntu` | In-VM user callers SSH as. |

Hetzner provider:

| Variable | Default | Purpose |
| --- | --- | --- |
| `HETZNER_API_TOKEN` | — (required) | Bearer token for the Hetzner Cloud API. |
| `HETZNER_LOCATION` | — (required) | Location for launches, e.g. `nbg1`, `fsn1`, `hel1`, `ash`. |
| `HETZNER_DEFAULT_IMAGE` | `ubuntu-24.04` | Image name/id used when the caller omits `image`. |
| `HETZNER_SERVER_TYPE` | `cx23` | Server type, e.g. `cx23`, `cx33`. Hetzner retires older generations (e.g. `cx22`); a deprecated type fails provisioning with a 422. |
| `HETZNER_API_TIMEOUT` | `30.0` | Timeout for Hetzner API calls. |
| `HETZNER_BOOTSTRAP_SSH_TIMEOUT_SECONDS` | `120.0` | ssh-keyscan retry budget for a fresh server. |
| `HETZNER_SSH_USERNAME` | `root` | In-VM user callers SSH as. |

A fresh Hetzner server has no firewall — port 22 is open and SSH is
key-only. Drukbox mints a per-VM ed25519 key in both networking modes;
there is no security-group or ingress-CIDR configuration to manage.

Docker provider:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DOCKER_DEFAULT_IMAGE` | `ghcr.io/clawhaven/drukbox/sandbox:latest` | Sandbox image with sshd; auto-pulled. Build `images/local/Dockerfile` to customize. |
| `DOCKER_SSH_USERNAME` | `root` | In-container user callers SSH as. |
| `DOCKER_BOOTSTRAP_SSH_TIMEOUT_SECONDS` | `30.0` | ssh-keyscan retry budget for a fresh container. |

The docker provider uses the host's configured Docker CLI, so the local
development path is to run drukbox from source on that host. The
published API image does not install a Docker CLI. If you containerize
this mode, build a custom image with a Docker CLI and mount or point it
at a daemon yourself (`DOCKER_HOST`, Docker Desktop, OrbStack, Colima);
that access is host-root-equivalent. Drukbox mints a per-VM ed25519 key
and publishes sshd on a random `127.0.0.1` port. See
[Local sandboxes with Docker](#local-sandboxes-with-docker) for setup and
the trust caveat.
