# Private AgenticOS demo on Coolify

[compose.yml](compose.yml) runs the upstream AgenticOS 1.52.0 API, worker,
frontend and one-time migration with PostgreSQL/pgvector and Valkey. The
application images are pinned by digest. This setup has no public routes or
host-published ports; access uses [tunnel.py](tunnel.py) on the demo computer.

## Deploy the stack

Create an isolated Docker Compose service in Coolify using `compose.yml`.
The host must already have Coolify's external `coolify` Docker network.
Leave every service's domain blank and retain `traefik.enable: false`.

Supply these values through Coolify's protected environment settings. Keep
credentials and deployment-specific configuration outside version control.

| Variable | Value |
| --- | --- |
| `SECRET_KEY` | Independent random application signing secret. |
| `API_KEY` | Independent random application API key setting. |
| `VAULT_MASTER_KEY` | Independent random master secret for stored credentials. |
| `POSTGRES_PASSWORD` | Independent random database password. |
| `REDIS_PASSWORD` | Independent random cache password. |
| `PUBLIC_SITE_URL` | `http://localhost:3130` |
| `PUBLIC_API_URL` | `http://localhost:8130` |
| `PUBLIC_WS_URL` | `ws://localhost:8130` |
| `CORS_ORIGINS` | `["http://localhost:3130"]` |

Use separate cryptographically random values, for example 64 hexadecimal
characters per secret. In this release, `VAULT_MASTER_KEY` is a string from
which the vault derives its key; it does not require Fernet encoding. Preserve
it securely alongside database backups: changing it prevents access to existing
vault entries.

Deploy and confirm that migration exits successfully and the five persistent
services become healthy. The configured memory limits total about 7 GiB, with
additional headroom needed for migrations, Docker, Coolify and other workloads.

Run the upstream bootstrap inside the API container to create the owner and
organization. Supply its password through a private input mechanism, rather
than a command argument or log. Bootstrap does not require a model credential.
Set the deployment's `signup_mode` to `closed` through administrator settings
before opening the demo to other users. See the upstream
[deployment guide](../../docs/deploy.md) and
[deployment settings](../../docs/deployment.md).

Add a provider credential to the AgenticOS vault, create a model profile, then
create and publish an agent. For an OpenAI-compatible gateway in 1.52.0, use
provider `litellm`, the gateway's verified `/v1` base URL, and a model selector
that the gateway supports. See [models](../../docs/models.md) and
[secrets](../../docs/secrets.md). Model requests use the configured provider and
may incur its charges.

For the personal account option, see
[Personal model connections](personal-model-connections.md). It describes owner
access, Claude subscription sign-in, API connections and the matching backend
migration required by the AI connections settings page. The native subscription
option also needs its [private runtime service](../claude-subscription/README.md).

## Open the private preview

On the computer running the demo browser, use Python with Paramiko installed
(the helper was syntax-checked with Python 3.14.3 and Paramiko 3.5.1).
Sign in to Azure CLI with permission to read the designated Key Vault secret.
That secret must hold an unencrypted OpenSSH or PEM private key authorized for
the VM. The SSH user needs Docker inspect access and TCP forwarding permission.

Verify the VM's SSH host fingerprint through an existing trusted connection or
the host console. Do not establish trust from an unauthenticated key scan alone.

Create a private JSON file outside the checkout. Replace every example value
below, including both exact container names shown by Coolify:

```json
{
  "host": "demo-vm.example.invalid",
  "host_key_sha256": "SHA256:REPLACE_WITH_VERIFIED_HOST_FINGERPRINT",
  "ssh_user": "root",
  "ssh_port": 22,
  "vault_name": "example-demo-vault",
  "ssh_secret_name": "example-demo-ssh-key",
  "mappings": [
    {
      "local_port": 3130,
      "container": "agenticos-frontend-EXACT-COOLIFY-SUFFIX",
      "container_port": 3000
    },
    {
      "local_port": 8130,
      "container": "agenticos-api-EXACT-COOLIFY-SUFFIX",
      "container_port": 8000
    }
  ]
}
```

From the repository root, run the helper and keep its terminal open:

```sh
python integrations/coolify-demo/tunnel.py --config /path/to/private-demo.json
```

The helper reads the SSH secret into memory, checks the host fingerprint,
resolves each exact container's current IPv4 address, and binds only
`127.0.0.1`. Open <http://localhost:3130> in a browser **on that same computer**.
A remote or cloud browser has a different localhost and cannot use this tunnel.

Check <http://localhost:3130/api/health> and
<http://localhost:8130/api/v1/health>, then sign in with the bootstrapped owner.
Keep the browser, API, WebSocket and CORS settings consistently on `localhost`.
Production authentication remains enabled; genuine HTTP localhost requests use
HttpOnly, SameSite=Lax session cookies without the HTTPS-only Secure flag.

## Limits and maintenance

- The tunnel does not reconnect automatically. Restart it after SSH loss or any
  deployment that replaces a mapped container. It permits at most 64 concurrent
  forwarded connections. Ctrl+C closes the listeners and connections.
- The helper is a foreground preview process, not an installed operating-system
  service. Windows forced process termination does not guarantee graceful cleanup.
- PostgreSQL and uploaded media use named volumes. Back them up before upgrades;
  deleting the service's volumes deletes its stored data. Valkey is disposable.
- Backend and frontend digests are fixed; database and cache image tags are
  mutable. Review upgrades and migrations before changing the deployed images.
- Optional sandbox, browser, OCR/ML and observability services are absent.
  Diagnostics collection and OAuth login buttons are disabled by this compose.
- Private access is limited to the computer running the tunnel. Shared or public
  access needs a separately reviewed deployment and authentication arrangement.
