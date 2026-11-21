# Yhub (Collaboration Server)

Yhub is the real-time collaboration server of Docs v6. It holds the content of every document.
The editors sync with it over a websocket. The backend reads and writes documents through its REST API.
It runs as its own sub-application: own `yhub.service` systemd user unit, own `/opt/docs/yhub`
directory, own published port.

## Why a Separate Unit

Yhub replicas keep no private state. They share two stores: a Redis (live state) and a PostgreSQL
database (persisted content). Any replica serves any document. The core caddy sends each request to
any healthy yhub host and does not pin a document to a host. The yhub hosts have their own life cycle,
so they have their own unit, compose file, hosts, and port. The `CADDY_YHUB_ENDPOINTS` value of
`st_docs_caddy_env` lists them.

The y-provider of Docs v5 is not this unit. In Docs v6 the y-provider only converts documents (markdown,
html, json to and from yjs). It runs in the core unit as the container `docs-y-provider`, with no published
port. The role removes the legacy `yprovider` unit from the hosts (see
[04-upgrade-v5-to-v6.md](04-upgrade-v5-to-v6.md)).

## Container Stack

```text
docs-yhub (docker.io/lasuite/impress-yhub), published on the host
  └── healthcheck: GET /collaboration/ready/v1 (checks PostgreSQL and Redis)
```

The image has no shell. A command must call `node` directly.

## Prerequisites

| Requirement | Value |
|-------------|-------|
| Platform | Debian Trixie |
| RAM | 512 MB minimum |
| PostgreSQL | An own database for yhub, not the Django database. Create it before the first deployment |
| Redis | Redis 6.2 or later, or Valkey |
| Depends on | Docs core application (public domain, JWKS of the backend) |

Create the database before the first deployment. When the database does not exist, yhub stops at start
with `database "<name>" does not exist` and never listens. The unit start fails and the role never runs
`init-db`. When the database exists but is empty, the container becomes healthy before the schema
exists. The unit starts, then the role runs `init-db`. Until the task ends, document reads fail. The
readiness route checks the connection to PostgreSQL and Redis, not the schema.

Follow these rules for Redis:

- Use a durable instance (AOF enabled). Yhub holds the live state of a document in Redis until a worker
  persists it to PostgreSQL. A lost Redis loses the data that is not yet persisted.
- Do not evict keys that have no expiry.
- Do not use the Redis of the Django cache. Give yhub its own instance.
- Set `REDIS_PREFIX` (default `yhub`) when the instance is shared with another service.

## Variable Reference

See [roles/docs/REFERENCE.md](../../roles/docs/REFERENCE.md) for the complete variable
reference.

## Key Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `st_docs_yhub_enabled` | Enable the yhub unit | `false` |
| `st_docs_yhub_dir` | Application directory | `/opt/docs/yhub` |
| `st_docs_yhub_port` | Host port for the yhub container | `50601` |
| `st_docs_tag` | Docker image tag, shared with the core images | `v6.1.0` |
| `st_docs_yhub_env` | Environment content. `REDIS` and `POSTGRES` are required. Do not set `PORT` | _(empty)_ |
| `st_docs_yhub_secret_files` | Secrets that yhub reads from files, such as `YHUB_JWT_PRIVATE_KEY` | `[]` |
| `st_docs_yhub_run_init_db` | Create or update the database schema at each deployment | `true` |
| `st_docs_yhub_rollback_enabled` | Rollback on failure | `false` |
| `CADDY_YHUB_ENDPOINTS` (in `st_docs_caddy_env`) | Space-separated `host:port` yhub upstreams, set on the **core** side | **(required)** |
| `YHUB_API_BASE_URL` (in `st_docs_backend_env`) | URL that the backend and the workers use to call yhub | **(required)** |

Example of `st_docs_yhub_env`:

```yaml
st_docs_yhub_env: |
  REDIS=redis://valkey.example.com:6379/0
  REDIS_PREFIX=yhub
  POSTGRES=postgres://yhub:{{ vault_yhub_db_password }}@db.example.com:5432/yhub?sslmode=require
  COLLABORATION_BACKEND_BASE_URL=https://docs.example.com
  COLLABORATION_SERVER_ORIGIN=https://docs.example.com
  Y_PROVIDER_API_KEY={{ vault_y_provider_api_key }}
```

The backend reads `Y_PROVIDER_API_KEY` too. Both values must be equal. The backend uses it to skip the API
throttling for the calls of yhub.

## Network & Ports

| Variable | Default | Container port |
|----------|---------|---------------|
| `st_docs_yhub_port` | `50601` | 3002 |

Open the port `50601` from the core hosts and from the workers hosts only. The caddy of each core host
and the backend call it. Do not open it to the internet.

## Routes

The core caddy publishes these routes of yhub on `/collaboration/`:

| Route | Use |
|-------|-----|
| `/collaboration/ws/` | Websocket of the editor |
| `/collaboration/ydoc/` | HTTP fallback of the editor |
| `/collaboration/activity/`, `/collaboration/changeset/` | Editing history |
| `/collaboration/rollback/` | Restore of a document to a point in its history |
| `/collaboration/jwks/` | Public key of yhub |

Every other `/collaboration/` path returns 404 on the core caddy. These routes stay internal:
`prune`, `reset-connections`, `migrate`, `create-ydoc`, `restore-ydoc`, `reset-ydoc`, and the probes
`ping` and `ready`. The backend calls the other routes through `YHUB_API_BASE_URL`. Nothing calls `ping`.
Caddy probes `ready` on each upstream.

## Scaling Notes

To add yhub capacity, deploy the role on more hosts. Then update `CADDY_YHUB_ENDPOINTS` on every core host.

- With st-cli, the hosts files give this key at each replay, so a manual edit does not survive. Run
  `st-cli bootstrap docs <env> -c yhub` with the new hosts list. Then run `st-cli bootstrap docs <env>`, so
  the docs unit gets the new list. Then run `st-cli deploy docs <env>`.
- With the role only, edit `CADDY_YHUB_ENDPOINTS` in `st_docs_caddy_env` and deploy the core unit again.

Caddy checks the health of each upstream on
`/collaboration/ready/v1` and skips an unhealthy host.

With rootless podman, a container cannot reach the IP address of its own host. It must use
`host.containers.internal`.

`CADDY_YHUB_ENDPOINTS` lists the yhub upstreams. When a yhub host is also a core host, st-cli writes
`host.containers.internal:50601`. It also writes the real address of each yhub host that another core
host can use. Caddy checks the health of each entry and drops the entries that it cannot reach.

`YHUB_API_BASE_URL` is one URL, for the backend on every core host and for every workers host. Follow
these rules:

- It can be `http://host.containers.internal:50601` only when every core host runs yhub and the workers
  run on core hosts.
- If not, it must be the address of a yhub host that is neither a core host nor a workers host, or the
  URL of an internal load balancer. A yhub host that is also a core or workers host cannot be this URL.
- Without a load balancer, the URL points at one yhub host only. That host is a single point of failure
  for the backend calls.

Write each host the same way (the same name or the same IP address) in every hosts prompt of st-cli.
St-cli compares the values as text to detect a shared host.

The workers hosts need access to the port `50601` of the yhub hosts.

`YHUB_ROLE` splits the server and the worker of yhub. Unset (or `all`), one process does both. `server`
accepts connections and routes but persists nothing. `worker` persists to PostgreSQL and binds no port.
Split them together or not at all. The role deploys one `yhub` unit, so the default is the right choice
unless you use a custom compose template.

## Keys

The backend and yhub authenticate each other with signed tokens. They share no secret.
`COLLABORATION_SERVER_SECRET` does not exist in Docs v6.

| Key | Variable | Where |
|-----|----------|-------|
| Backend key | `JWT_PRIVATE_KEY` | `st_docs_backend_secret_files` (also used by the workers) |
| Yhub key | `YHUB_JWT_PRIVATE_KEY` | `st_docs_yhub_secret_files` |

Follow these rules:

- Each key is an RSA private key in PKCS#8 PEM format. Yhub refuses another format.
- Each side reads the JWKS of the other side: the backend publishes `/api/v1.0/jwks`, yhub publishes
  `/collaboration/jwks/v1`. No side holds a copy of the other key.
- Do not use one key for both sides.
- Without `YHUB_JWT_PRIVATE_KEY`, yhub serves documents but does not tell the backend about edits. The
  `updated_at` of a document then stops following the edits.

Example:

```yaml
st_docs_backend_secret_files:
  - env: JWT_PRIVATE_KEY
    content: "{{ vault_jwt_private_key }}"
st_docs_yhub_secret_files:
  - env: YHUB_JWT_PRIVATE_KEY
    content: "{{ vault_yhub_jwt_private_key }}"
```

To create a key, run `st-cli generate-keypairs docs <env>` (it prints both keys), or run:

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048
```

To rotate a key, replace the key of one side and deploy that side. The other side reads the new public
key from the JWKS. Tokens are short-lived. Check that the documents still open after the rotation.

## Database Schema

Yhub never creates its schema when it starts. The role runs this command after the yhub unit starts, with
`run_once: true`:

```bash
podman-compose run --rm --name docs_yhub_init_db yhub node dist/init-db.js --attempts=1
```

The command is idempotent. The role cannot create the database: when it does not exist, yhub stops at
start, the unit start fails, and `init-db` does not run. Create the database before the first
deployment. The command prints PostgreSQL `NOTICE` lines and a success message on every run. Its output
does not tell a change from no change, so the role task never reports "changed". The role runs
`init-db` after the unit start, like the Django `migrate`
task. After an upgrade that adds a table, yhub can fail some document reads for a few seconds until the
task ends. The role retries the task 3 times. Set `st_docs_yhub_run_init_db: false` to skip it.

To run the command by hand:

```bash
st-cli oneoff docs <env> -c yhub -s yhub -- node dist/init-db.js --attempts=1
```

The image has no shell, so a command is mandatory. Run it again after each upgrade that adds a table.

## Troubleshooting

```bash
ssh <host>
sudo -iu docs

# Service lifecycle
systemctl --user status yhub.service
systemctl --user start yhub.service
systemctl --user stop yhub.service

# Logs
journalctl --user -u yhub.service -f
journalctl --user -u yhub.service --since today
journalctl --user -u yhub.service --since "3 hours ago"

# Containers
podman-compose -f /opt/docs/yhub/compose.yaml ps

# Check yhub health (PostgreSQL and Redis)
curl -s http://localhost:50601/collaboration/ready/v1
```

Common errors:

- The unit does not start: yhub stops with `database "<name>" does not exist`, or the container is not
  healthy. Check that the `yhub` database exists and that `POSTGRES` and `REDIS` are correct.
- A document read fails with `relation "..." does not exist`: the schema is missing. Run the `init-db`
  command.
- A document opens empty: the migration of Docs v5 documents did not run. See
  [04-upgrade-v5-to-v6.md](04-upgrade-v5-to-v6.md).
