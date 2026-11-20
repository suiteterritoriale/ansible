# Contacts Application

The `contacts` role deploys the [Contacts](https://github.com/suitenumerique/contacts)
application from La Suite Territoriale: personal and organization address books, groups, a
CardDAV server, and an external API that the other apps of the Suite use to suggest people.

The role deploys multiple independent sub-applications under the `contacts` Unix user, each as a
separate systemd user unit. All sub-apps are disabled by default and must be explicitly enabled.

> [!NOTE]
> This collection does not provision PostgreSQL or Redis. You must provide them externally
> before you deploy Contacts.

## Sub-Applications

| Sub-App | Description | Doc |
|---------|-------------|-----|
| **contacts** | Core web application (frontend + backend) | This page |
| **workers** | Dramatiq worker | [02-workers.md](02-workers.md) |

## Container Stack

```text
contacts-frontend (ghcr.io/suitenumerique/contacts-frontend, Caddy), published on the host
  ├── /api/*, /carddav, /carddav/*, /.well-known/carddav, /admin/*, /static/*, /__heartbeat__/
  │     → contacts-backend (ghcr.io/suitenumerique/contacts-backend, gunicorn)
  └── everything else → the SPA, served by the same Caddy
```

The frontend image is a Caddy server. It serves the SPA and proxies the backend paths to
`CONTACTS_FRONTEND_BACKEND_SERVER`. Set it in `st_contacts_frontend_env`, see
[Frontend Environment](#frontend-environment).

## Prerequisites

| Requirement | Value |
|-------------|-------|
| Platform | Debian Trixie |
| RAM | 1 GB minimum |
| Disk | 1 GB for images |
| Database | External PostgreSQL (configured via env) |
| Redis | External Redis (configured via env) |
| Identity | An OIDC provider, e.g. Keycloak (see [02-keycloak](../02-keycloak/01-keycloak.md)) |

## Variable Reference

See [roles/contacts/REFERENCE.md](../../roles/contacts/REFERENCE.md) for the complete variable reference.

## Key Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `st_contacts_public_host` | Public hostname for the app | **(required)** |
| `st_contacts_enabled` | Enable the contacts app | `false` |
| `st_contacts_tag` | Tag of the frontend and backend images | `main` |
| `st_contacts_dir` | Application directory | `/opt/contacts/contacts` |
| `st_contacts_uid` | Unix UID for the contacts user | `1111` |
| `st_contacts_port` | Host port for the frontend | `51100` |
| `st_contacts_backend_env` | Backend environment content | _(empty)_ |
| `st_contacts_frontend_env` | Frontend (Caddy) environment content | _(empty)_ |
| `st_contacts_backend_run_migrations` | Run Django migrations on deploy | `true` |

> [!NOTE]
> Contacts has no release yet. The images default to the `main` tag, which moves with each
> merge upstream. Do not pin `main` by digest: the upstream CI deletes untagged images, so the
> digest disappears from the registry when `main` moves. Pin the first release when it exists.

## Network & Ports

| Variable | Default | Container port |
|----------|---------|---------------|
| `st_contacts_port` | `51100` | 8080 (frontend) |

The frontend is the only container published to the host. The backend is only reachable from
the frontend via the Podman bridge network.

## Backend Environment

Example of `st_contacts_backend_env`:

```text
DJANGO_SETTINGS_MODULE=contacts.settings
DJANGO_CONFIGURATION=Production
DJANGO_SECRET_KEY=<secret>
DJANGO_ALLOWED_HOSTS=contacts.example.org
DJANGO_CSRF_TRUSTED_ORIGINS=https://contacts.example.org
# Key list that encrypts the stored secrets. Required in Production.
SALT_KEY=<secret>
# The frontend Caddy sets X-Forwarded-For.
NUM_PROXIES=1
DB_HOST=postgres.example.org
DB_PORT=5432
DB_NAME=contacts
DB_USER=contacts
DB_PASSWORD=<secret>
REDIS_URL=redis://:<password>@redis.example.org:6379/0
DRAMATIQ_BROKER_URL=redis://:<password>@redis.example.org:6379/0
DRAMATIQ_RESULT_BACKEND_URL=redis://:<password>@redis.example.org:6379/1
OIDC_RP_CLIENT_ID=contacts
OIDC_RP_CLIENT_SECRET=<secret>
OIDC_RP_SCOPES=openid email
OIDC_OP_JWKS_ENDPOINT=https://auth.example.org/realms/main/protocol/openid-connect/certs
OIDC_OP_AUTHORIZATION_ENDPOINT=https://auth.example.org/realms/main/protocol/openid-connect/auth
OIDC_OP_TOKEN_ENDPOINT=https://auth.example.org/realms/main/protocol/openid-connect/token
OIDC_OP_USER_ENDPOINT=https://auth.example.org/realms/main/protocol/openid-connect/userinfo
OIDC_OP_LOGOUT_ENDPOINT=https://auth.example.org/realms/main/protocol/openid-connect/logout
LOGIN_REDIRECT_URL=https://contacts.example.org
LOGIN_REDIRECT_URL_FAILURE=https://contacts.example.org
LOGOUT_REDIRECT_URL=https://contacts.example.org
```

To let the other apps of the Suite call the external API (`/external_api/v1.0/`) with the
access token of their user, also set `OIDC_RESOURCE_SERVER_ENABLED=True`,
`OIDC_OP_INTROSPECTION_ENDPOINT`, `OIDC_RS_CLIENT_ID`, `OIDC_RS_CLIENT_SECRET` and
`OIDC_RS_ALLOWED_AUDIENCES`. See the upstream
[resource server guide](https://github.com/suitenumerique/contacts/blob/main/docs/resource_server.md).

## Frontend Environment

The frontend Caddy reads these variables. Set them as lines in `st_contacts_frontend_env`:

```text
CONTACTS_FRONTEND_BACKEND_SERVER=contacts-backend:8000
```

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTACTS_FRONTEND_BACKEND_SERVER` | `localhost:8000` | **Required.** Address of the backend. Set `contacts-backend:8000`. |
| `DJANGO_ADMIN_URL` | `admin` | Django admin path, without slashes. Set the same value in the backend env. |
| `DJANGO_ADMIN_IP_ALLOWLIST` | `0.0.0.0/0 ::/0` | Space-separated CIDR list of client IPs allowed on the admin URL. Caddy answers 403 to the others. |
| `CONTACTS_FRONTEND_TRUSTED_PROXIES` | _(empty)_ | Space-separated CIDR list of upstream proxies whose `X-Forwarded-For` sets the client IP. Empty: the TCP peer is the client. |

Follow these rules:

- If you set `DJANGO_ADMIN_IP_ALLOWLIST`, add your own administration network. When the list
  does not include it, you lose access to the Django admin.
- Do not set `DJANGO_ADMIN_IP_ALLOWLIST` to an empty value. An empty list denies every admin
  request. Remove the line to allow all.
- Behind a load balancer, set `CONTACTS_FRONTEND_TRUSTED_PROXIES` to its range. When you do not,
  Caddy uses the load balancer IP as the client IP.

## Data & Volumes

The contacts application is stateless: it stores data in an external PostgreSQL database. No
persistent bind mounts are needed.

## Database Migrations

The role runs `python manage.py migrate` via `podman-compose run` after deployment. This task
has `run_once: true`, which limits execution to one host per Ansible batch. When `serial:` is
used, each host is its own batch, so `run_once: true` does **not** prevent migrations from
running on every host. Set `st_contacts_backend_run_migrations: false` on all hosts except the
first to avoid duplicate migrations. For example:

```yaml
st_contacts_backend_run_migrations: "{{ true if inventory_hostname == ansible_play_hosts_all[0] else false }}"
```

## Custom Environment

You can either:

- Set `st_contacts_backend_env` / `st_contacts_frontend_env` to provide env content inline.
- Set the matching `_env_template` variable to use a custom template.

## Secrets from Files

The contacts backend reads some secrets from a file. The backend reads the file when the variable
`<NAME>_FILE` holds the path of the file. The role writes these files and sets these variables for you.

Set `st_contacts_backend_secret_files` to a list. Each item has the key `env`, the name of the variable, and one
of `src` (a template) or `content` (an inline value):

```yaml
st_contacts_backend_secret_files:
  - env: DB_PASSWORD
    content: "{{ vault_contacts_db_password }}"
  - env: OIDC_RP_CLIENT_SECRET
    src: "contacts_oidc_secret.j2"
```

For each item, the role:

- writes the file `secrets/<env>` in the application directory (mode `0440`), for example
  `{{ st_contacts_dir }}/secrets/DB_PASSWORD`;
- mounts the `secrets` directory read-only at `/run/secrets` in the container;
- sets `<ENV>_FILE` in the compose `environment`, for example `DB_PASSWORD_FILE: /run/secrets/DB_PASSWORD`.

The role removes the files of the items that you remove from the list.
It removes the `secrets` directory when the list is empty.

The contacts workers use `st_contacts_workers_secret_files`. The default value is `st_contacts_backend_secret_files`.

The file has priority over the same variable in `st_contacts_backend_env`. If both are set, the backend uses the file.

Upstream contacts supports `_FILE` for these variables (`SecretFileValue` in `src/backend/contacts/settings.py`):

- `DJANGO_SECRET_KEY`: Django secret key.
- `DB_PASSWORD`: Database password.
- `OIDC_RP_CLIENT_SECRET`: OIDC client secret.
- `OIDC_RS_CLIENT_SECRET`: OIDC resource server client secret.

Upstream does not support `_FILE` for other variables, `SALT_KEY` included.
If you add an item for another variable, the backend ignores the file.

If you use a custom compose template (`st_contacts_compose_template` or `st_contacts_workers_compose_template`),
the template must declare the `environment:` and `volumes:` entries itself.

If `DATABASE_URL` is set, the DB settings come from the URL. Then `DB_PASSWORD_FILE` has no effect.

## First Deploy

Create a superuser once, after the first deploy:

```bash
sudo -iu contacts
podman-compose -f /opt/contacts/contacts/compose.yaml run --rm backend python manage.py createsuperuser --email admin@example.org --password '<password>'
```

When a user with this email exists, for example after an OIDC login, the command makes this
user a superuser.

## Bootstrap with st-cli

`st-cli bootstrap` prompts for the Contacts settings: the domain, the database, `REDIS_URL`,
the identity provider, and cadvisor. Contacts has no S3 storage and sends no email, so
`st-cli` does not ask for them. It generates `DJANGO_SECRET_KEY` and `SALT_KEY`, derives
`DRAMATIQ_BROKER_URL` and `DRAMATIQ_RESULT_BACKEND_URL` from `REDIS_URL`, and writes the
frontend env with `CONTACTS_FRONTEND_BACKEND_SERVER` and
`CONTACTS_FRONTEND_TRUSTED_PROXIES=private_ranges`. See
[00-getting-started/01-st-cli.md](../00-getting-started/01-st-cli.md) for general st-cli usage.

## Troubleshooting

```bash
ssh <host>
sudo -iu contacts

# Service lifecycle
systemctl --user status contacts.service
systemctl --user start contacts.service
systemctl --user stop contacts.service

# Logs
journalctl --user -u contacts.service -f
journalctl --user -u contacts.service --since today

# Containers
podman-compose -f /opt/contacts/contacts/compose.yaml ps
```
