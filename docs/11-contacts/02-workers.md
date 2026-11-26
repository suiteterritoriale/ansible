# Contacts Workers

Dramatiq worker for the Contacts application. It uses the same backend image with
`python worker.py`.

## Features That Run on the Workers

In `Production`, the backend queues the Dramatiq tasks in Redis. Without this unit, the features
below do not run.

| Feature | Task | When it fires |
|---------|------|---------------|
| vCard and CSV import | `core.tasks.import_contacts_task` | A user imports a file into their contacts, or an administrator into the organization address book. |

## Container Stack

```text
contacts-worker (ghcr.io/suitenumerique/contacts-backend)
  └── python worker.py
```

## Prerequisites

| Requirement | Value |
|-------------|-------|
| Platform | Debian Trixie |
| RAM | 512 MB minimum |
| Depends on | Contacts application (shared database, Redis, env) |

## Variable Reference

See [roles/contacts/REFERENCE.md](../../roles/contacts/REFERENCE.md) for the complete variable reference.

## Key Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `st_contacts_workers_enabled` | Enable the workers | `false` |
| `st_contacts_workers_dir` | Application directory | `/opt/contacts/workers` |
| `st_contacts_workers_env` | Environment content | `{{ st_contacts_backend_env }}` |
| `st_contacts_workers_rollback_enabled` | Rollback on failure | `false` |

## Network & Ports

No ports are published to the host.

## Data & Volumes

Stateless. No persistent bind mounts.

## Troubleshooting

```bash
ssh <host>
sudo -iu contacts

# Service lifecycle
systemctl --user status workers.service
systemctl --user start workers.service
systemctl --user stop workers.service

# Logs
journalctl --user -u workers.service -f
journalctl --user -u workers.service --since today

# Containers
podman-compose -f /opt/contacts/workers/compose.yaml ps

# Healthcheck: exit 0 if the worker of this container answers a ping
podman exec contacts-worker python worker.py --ping
```
