# Docs Application

The `docs` role deploys the [Docs](https://github.com/suitenumerique/docs) collaborative
document editor from La Suite Territoriale (upstream image name "impress").

The role deploys multiple independent sub-applications under the `docs` Unix user, each as a
separate systemd user unit. All sub-apps are disabled by default and must be explicitly enabled.

> [!NOTE]
> This collection does not provision PostgreSQL, Redis, S3-compatible storage, or an OIDC
> provider. You must provide these externally before deploying Docs. We recommend using
> managed database services from cloud providers such as [Scalingo](https://scalingo.com) or
> [Scaleway](https://www.scaleway.com).

## Sub-Applications

| Sub-App | Description | Doc |
|---------|-------------|-----|
| **docs** | Core web application (caddy + frontend + backend + conversion services) | This page |
| **workers** | Celery background workers | [02-workers.md](02-workers.md) |
| **yhub** | Real-time collaboration server, holds the document content | [03-yhub.md](03-yhub.md) |

To upgrade an instance from Docs v5, read [04-upgrade-v5-to-v6.md](04-upgrade-v5-to-v6.md) first.

## Container Stack

```text
docs-caddy (docker.io/caddy), published on the host
  ├── /api*, /admin, /admin/*, /external_api/*, /static/* → docs-backend (docker.io/lasuite/impress-backend)
  ├── /media/* → S3, forward_auth against docs-backend
  ├── /collaboration/(ws|ydoc|rollback|changeset|activity|jwks)/ → yhub hosts (see 03-yhub.md)
  ├── other /collaboration/* paths → 404
  └── everything else → docs-frontend (docker.io/lasuite/impress-frontend, stock SPA nginx conf)

docs-docspec (ghcr.io/docspecio/api), no published port
  └── backend-only .docx conversion for the import feature (http://docspec:4000/conversion)

docs-y-provider (docker.io/lasuite/impress-y-provider), no published port
  └── backend-only conversion of markdown, html and json to and from yjs (http://y-provider:4444/api/)
```

Caddy owns the host port and dispatches each request to the backend, the frontend, S3, or the
yhub unit. The y-provider serves no collaboration route in Docs v6. It only converts documents.

## Prerequisites

| Requirement | Value |
|-------------|-------|
| Platform | Debian Trixie |
| RAM | 1 GB minimum |
| Disk | 2 GB for images + data |
| Database | External PostgreSQL (configured via env) |
| Redis | External Redis (configured via env) |
| yhub database | A second PostgreSQL database for the yhub unit, created before the first deployment (see [03-yhub.md](03-yhub.md)) |
| yhub Redis | A durable Redis 6.2 or later, or Valkey, for the yhub unit. Do not use the Django cache (see [03-yhub.md](03-yhub.md)) |
| Identity | An OIDC provider, e.g. Keycloak (see [02-keycloak](../02-keycloak/01-keycloak.md)) |
| S3 Storage | S3-compatible object storage for document media |

## Variable Reference

See [roles/docs/REFERENCE.md](../../roles/docs/REFERENCE.md) for the complete variable
reference.

## Key Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `st_docs_enabled` | Enable the docs app | `false` |
| `st_docs_public_host` | Public hostname for the app | **(required)** |
| `st_docs_tag` | Docker image tag (shared by frontend, backend, y-provider, yhub) | `v6.1.0` |
| `st_docs_dir` | Application directory | `/opt/docs/docs` |
| `st_docs_uid` | Unix UID for the docs user | `1106` |
| `st_docs_port` | Host port for the caddy edge | `50600` |
| `st_docs_backend_env` | Backend environment content. It needs `YHUB_API_BASE_URL`, `COLLABORATION_WS_URL`, `Y_PROVIDER_API_BASE_URL` and `Y_PROVIDER_API_KEY` (same value as in `st_docs_yhub_env`) | _(empty)_ |
| `API_DOCUMENT_THROTTLE_RATE` (in `st_docs_backend_env`) | Anonymous throttle of the documents API, default `80/minute`. See [04-upgrade-v5-to-v6.md](04-upgrade-v5-to-v6.md#throttle) | `80/minute` |
| `st_docs_backend_secret_files` | Secrets that the backend reads from files, such as `JWT_PRIVATE_KEY` | `[]` |
| `st_docs_yprovider_env` | Env file of the y-provider conversion service in the docs unit | _(empty)_ |
| `st_docs_caddy_env` | Caddy env content: `CADDY_S3_*` + `CADDY_YHUB_ENDPOINTS` (space-separated `host:port` yhub upstreams for the `/collaboration/*` route), plus optional `CADDY_ADMIN_IP_ALLOWLIST` / `CADDY_TRUSTED_PROXIES` | _(empty, required keys)_ |
| `st_docs_yprovider_legacy_cleanup_enabled` | Remove the legacy `yprovider` unit of Docs v5 from the hosts | `true` |
| `st_docs_frontend_logo_src` | Local path to an optional custom logo (svg) | _(unset)_ |
| `st_docs_theme_customization_src` | Local path to an optional theme customization JSON | _(unset)_ |
| `st_docs_backend_run_migrations` | Run Django migrations on deploy | `true` |

## Network & Ports

| Variable | Default | Container port |
|----------|---------|---------------|
| `st_docs_port` | `50600` | 50600 (caddy) |

Caddy listens on `50600` inside its own container and is the only container published to the
host. The frontend and backend are only reachable from caddy via the Podman bridge network.

## Django Admin IP Allowlist

The caddy edge adds two optional environment variables. Set them as lines in `st_docs_caddy_env`.

| Variable | Default | Description |
|----------|---------|--------------|
| `CADDY_ADMIN_IP_ALLOWLIST` | `0.0.0.0/0 ::/0` | Space-separated CIDR list of client IPs allowed on `/admin`, `/admin/*`, and `/admin;*`. Caddy answers 403 to a denied request. |
| `CADDY_TRUSTED_PROXIES` | `private_ranges` | Space-separated CIDR list of upstream proxies whose `X-Forwarded-For` sets the client IP. |

Example:

```yaml
st_docs_caddy_env: |
  CADDY_S3_PROTOCOL=https
  CADDY_S3_HOST=s3.example.com
  CADDY_S3_BUCKET=docs-media-storage
  CADDY_YHUB_ENDPOINTS=yhub1.example.com:50601 yhub2.example.com:50601
  # Load balancer range: trusted proxy only (default: private_ranges).
  CADDY_TRUSTED_PROXIES=203.0.113.0/24
  # Operator network allowed on the Django admin URL (default: allow all).
  CADDY_ADMIN_IP_ALLOWLIST=198.51.100.0/24
```

Follow these rules:

- If you set `CADDY_ADMIN_IP_ALLOWLIST`, add your own administration network. When the list
  does not include it, you lose access to the Django admin.
- Do not set `CADDY_ADMIN_IP_ALLOWLIST` to an empty value. An empty list denies every admin
  request. Remove the line to allow all.
- `CADDY_TRUSTED_PROXIES` must cover the load balancer. When it does not, Caddy uses the load
  balancer IP as the client IP. The allowlist then applies to that IP, not to the client.
- Do not keep the `private_ranges` default when untrusted machines share the private network
  with caddy.
- Caddy walks `X-Forwarded-For` right to left, so a client cannot set its own client IP.
- `st-cli bootstrap` keeps these lines on a Modify or a silent replay. An Override replay
  drops them. Add them back by hand.

## S3 Media Auth

Requests under `/media/*` are proxied straight to S3 (`CADDY_S3_PROTOCOL` / `CADDY_S3_HOST` /
`CADDY_S3_BUCKET`), but caddy first runs a `forward_auth` subrequest against the backend
endpoint `/api/v1.0/documents/media-auth/`. Only a request the backend approves reaches the
object storage; this mirrors how the upstream nginx ingress protects media downloads.

## S3 Retention

In Docs v6 the content of a document lives in the yhub database. The bucket holds the attachments and
the legacy `<document-id>/file` objects of Docs v5. You must keep the bucket versioning and these
objects. Do not delete them before the migration of the documents ends (see
[04-upgrade-v5-to-v6.md](04-upgrade-v5-to-v6.md)).

Docs never deletes objects from the bucket. The trash retention (`TRASHBIN_CUTOFF_DAYS`,
default 30 days) only hides expired documents from the trashbin — the database rows, the
attachments, the legacy objects, and all object versions stay in S3 forever. No task or
scheduled job purges them.

What you can do to reclaim the space of one document tree is to run the upstream `clean_document` management
command manually: `st-cli oneoff docs <env> -- python manage.py clean_document --force <uuid>`
— it purges the content and attachments, versions included (`--force` is required when
`DEBUG` is off, so always in production).

## Document Import (docspec)

The compose ships a `docs-docspec` container by default. [DocSpec](https://github.com/docspecio/api)
is a small, stateless conversion service (an Elixir API): it converts `.docx` documents into the
BlockNote JSON format the editor uses. The backend calls it server-side at
`http://docspec:4000/conversion` when a user imports a `.docx` file; `.md` imports go through the
y-provider instead. The container publishes no port, keeps no data, and needs no configuration.
The import feature itself is switched on by `CONVERSION_UPLOAD_ENABLED=true` in the backend env.

## Data & Volumes

The docs application is stateless: it stores data in an external PostgreSQL database and uses
S3-compatible storage for media files. No persistent bind mounts are needed for the core
application, other than the optional theme file below.

## Database Migrations

The role runs `python manage.py migrate` via `podman-compose run` after deployment of the docs unit.
The yhub unit has its own schema task (see [03-yhub.md](03-yhub.md)). The Django `migrate` task
has `run_once: true`, so it executes once per play. If your deployment uses `serial:`, set
`st_docs_backend_run_migrations: false` on all hosts except one to avoid running migrations
multiple times.

## Custom Environment

You can either:

- Set `st_docs_backend_env` / `st_docs_frontend_env` / `st_docs_caddy_env` / `st_docs_yprovider_env`
  to provide env content inline
- Set the matching `_env_template` variable to use a custom template

## Secrets from Files

The docs backend reads some secrets from a file. The backend reads the file when the variable
`<NAME>_FILE` holds the path of the file. The role writes these files and sets these variables for you.

Set `st_docs_backend_secret_files` to a list. Each item has the key `env`, the name of the variable, and one
of `src` (a template) or `content` (an inline value):

```yaml
st_docs_backend_secret_files:
  - env: DB_PASSWORD
    content: "{{ vault_docs_db_password }}"
  - env: AWS_S3_SECRET_ACCESS_KEY
    src: "docs_s3_secret.j2"
```

For each item, the role:

- writes the file `secrets/<env>` in the application directory (mode `0440`), for example
  `{{ st_docs_dir }}/secrets/DB_PASSWORD`;
- mounts the `secrets` directory read-only at `/run/secrets` in the container;
- sets `<ENV>_FILE` in the compose `environment`, for example `DB_PASSWORD_FILE: /run/secrets/DB_PASSWORD`.

The role removes the files of the items that you remove from the list.
It removes the `secrets` directory when the list is empty.

The docs workers use `st_docs_workers_secret_files`. The default value is `st_docs_backend_secret_files`.

The file has priority over the same variable in `st_docs_backend_env`. If both are set, the backend uses the file.

Upstream docs `v6.1.0` supports `_FILE` for these variables (`SecretFileValue` in `src/backend/impress/settings.py`):

- `DJANGO_SECRET_KEY`: Django secret key.
- `DB_PASSWORD`: Database password.
- `AWS_S3_ACCESS_KEY_ID`: S3 access key.
- `AWS_S3_SECRET_ACCESS_KEY`: S3 secret key.
- `DJANGO_EMAIL_HOST_PASSWORD`: SMTP password.
- `OIDC_RP_CLIENT_SECRET`: OIDC client secret.
- `POSTHOG_KEY`: PostHog key.
- `Y_PROVIDER_API_KEY`: Key that yhub sends to the backend to skip the API throttling.
- `PROMETHEUS_API_KEY`: Key that protects the `/metrics` endpoint.
- `JWT_PRIVATE_KEY`: RSA private key (PKCS#8 PEM) that signs the tokens for yhub and the y-provider.
- `MISTRAL_SDK_API_KEY`: Mistral API key.
- `OPENAI_SDK_API_KEY`: OpenAI API key.
- `AI_API_KEY`: Former name of `OPENAI_SDK_API_KEY`.
- `LANGFUSE_SECRET_KEY`: Langfuse secret key.

Upstream does not support `_FILE` for other variables.
If you add an item for another variable, the backend ignores the file.
Multi-line values, such as a PEM key, work with `content: |` or with a template.
`JWT_PRIVATE_KEY` is the only variable of this list that holds a PEM key:

```yaml
st_docs_backend_secret_files:
  - env: JWT_PRIVATE_KEY
    content: "{{ vault_jwt_private_key }}"
```

The workers use the same list. They need the key to call yhub.

If you use a custom compose template (`st_docs_compose_template` or `st_docs_workers_compose_template`),
the template must declare the `environment:` and `volumes:` entries itself.

If `DATABASE_URL` is set, the DB settings come from the URL. Then `DB_PASSWORD_FILE` has no effect.

The y-provider does not read these files. It reads `COLLABORATION_BACKEND_BASE_URL` (and optionally
`COLLABORATION_SERVER_ORIGIN`) from `st_docs_yprovider_env`. The yhub unit has its own list,
`st_docs_yhub_secret_files` (see [03-yhub.md](03-yhub.md)).

## Custom Theme

You can override the default Docs theme without rebuilding the image. Set
`st_docs_theme_customization_src` to the path of a theme customization JSON file on the Ansible
controller (use an absolute path). When set, the role copies the file to the host and mounts it
read-only over the backend's default `THEME_CUSTOMIZATION_FILE_PATH`
(`/app/impress/configuration/theme/default.json`). The backend serves the JSON to the browser
through its `/api/v1.0/config/` endpoint — the frontend never reads the file itself.

> [!NOTE]
> The backend caches the parsed JSON in Redis for `THEME_CUSTOMIZATION_CACHE_TIMEOUT` seconds
> (default: 24 hours), and a backend restart does not clear Redis. Set a lower timeout in the
> backend env while you iterate on the theme, or expect a delay before a change appears.

To apply a theme change immediately, delete the cached key with a one-off command:

```bash
st-cli oneoff docs <env> -- python manage.py shell -c "from django.core.cache import cache; from django.conf import settings; from django.utils.text import slugify; cache.delete(f'theme_customization_{slugify(settings.THEME_CUSTOMIZATION_FILE_PATH)}')"
```

Do not use `cache.clear()` instead: django-redis implements it as a database flush, and the
sessions live in the same Redis — it logs every user out.

You can also set the `FRONTEND_THEME` and `FRONTEND_CSS_URL` backend environment keys for
further customization.

## Custom Logo

Set `st_docs_frontend_logo_src` to the path of a logo file (svg) on the Ansible controller
(use an absolute path). The role copies it to the host and mounts it read-only over
`/app/assets/icon-docs.svg` in the frontend container. Mirrors meet's
`st_meet_frontend_logo_src`.

How it works: the theme JSON decides which URL the logo spots load — the built-in default theme
points `header.icon.src` and the footer logo at `/assets/icon-docs.svg` — and the frontend
serves the bytes of that URL. The mount replaces the bytes, so the header, the left panel, and
the footer show your logo without a theme JSON. A custom theme JSON
(`st_docs_theme_customization_src`) can instead point `header.icon.src` at any URL; it then
bypasses the mount.

> [!NOTE]
> The bottom section of the home page embeds the icon at build time, so the mount does not
> change it. All the theme-driven spots (header, left panel, footer) do change.

## Bootstrap with st-cli

`st-cli bootstrap docs <env>` writes the `docs`, `yhub` and `workers` units. With the ansible-vault
backend, it generates the two RSA keys of Docs v6 and deploys them as secret files. With the hashi_vault
backend, you create the keys with `st-cli generate-keypairs docs <env>` and give the lookup terms.
St-cli builds `CADDY_YHUB_ENDPOINTS` and `YHUB_API_BASE_URL` from the yhub hosts you enter during the
questionnaire. See [03-yhub.md](03-yhub.md) for the key and endpoint
details, and [00-getting-started/01-st-cli.md](../00-getting-started/01-st-cli.md) for general st-cli usage.

## Troubleshooting

```bash
ssh <host>
sudo -iu docs

# Service lifecycle
systemctl --user status docs.service
systemctl --user start docs.service
systemctl --user stop docs.service

# Logs
journalctl --user -u docs.service -f
journalctl --user -u docs.service --since today
journalctl --user -u docs.service --since "3 hours ago"

# Containers
podman-compose -f /opt/docs/docs/compose.yaml ps
```
