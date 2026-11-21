<!-- BEGIN_ANSIBLE_DOCS -->
# Ansible Role: suitenumerique.st.docs
Version: 0.7.0
This role deploys a Docs instance from La Suite Territoriale on a rootless podman base on Debian systems.

Tags: suiteterritoriale, system

## Requirements

| Platform | Versions |
| -------- | -------- |
| Debian | trixie |

## Role Arguments

### Entrypoint: main

Installs and configures the docs application from La Suite Territoriale on Debian systems.

|Option|Description|Type|Required|Default|
|---|---|---|---|---|
| st_docs_uid | UID of the `docs` user, used for the podman role. | int | no | `1106` |
| st_docs_gid | GID of the `docs` group, used for the podman role. | int | no | `{{ st_docs_uid }}` |
| st_docs_registries | Optional private container registries to login the `docs` user onto. | list of `dict` | no |  |
| st_docs_public_host | The public hostname used to access the docs application. | str | no |  |
| st_docs_enabled | Triggers the installation of docs. | bool | no | `False` |
| st_docs_dir | Remote path to the base directory for docs app. | str | no | `/opt/docs/docs` |
| st_docs_port | The host published port for the docs frontend. | str | no | `50600` |
| st_docs_frontend_image | Image repository for the docs frontend. | str | no | `docker.io/lasuite/impress-frontend` |
| st_docs_backend_image | Image repository for the docs backend. | str | no | `docker.io/lasuite/impress-backend` |
| st_docs_yprovider_image | Image repository for the docs y-provider conversion service. | str | no | `docker.io/lasuite/impress-y-provider` |
| st_docs_tag | Tag of the docs docker images to deploy. | str | no | `v6.1.0` |
| st_docs_backend_env_template | Local path to the custom template to use for docs backend env file. | str | no | `docs/backend_env.j2` |
| st_docs_backend_env | Content of the default backend_env_template, not used if st_docs_backend_env_template is defined. | str | no |  |
| st_docs_backend_secret_files | Secrets that the container reads from files. Each item has the key "env" (the variable name in upper case) and one of the keys "src" (local template) or "content" (inline value). The role writes the file "secrets/<env>" in the application directory. The role mounts the "secrets" directory read-only at /run/secrets. The role sets "<ENV>_FILE" in the compose environment. The "<ENV>_FILE" variable has priority over the same variable in the env content. | list of `dict` | no | `[]` |
| st_docs_backend_run_migrations | Whether to run database migrations on docs backend startup. | bool | no | `True` |
| st_docs_frontend_env_template | Local path to the custom template to use for docs frontend env file. | str | no | `docs/frontend_env.j2` |
| st_docs_frontend_env | Content of the default frontend_env_template, not used if st_docs_frontend_env_template is defined. | str | no |  |
| st_docs_caddy_env_template | Local path to the custom template to use for docs caddy env file. | str | no | `docs/caddy_env.j2` |
| st_docs_caddy_env | Content of the default caddy_env_template, not used if st_docs_caddy_env_template is defined. The Caddyfile requires CADDY_S3_PROTOCOL, CADDY_S3_HOST, CADDY_S3_BUCKET and CADDY_YHUB_ENDPOINTS (a space-separated host:port list of yhub upstreams; any replica serves any document). Optional: CADDY_ADMIN_IP_ALLOWLIST (space-separated CIDR list of client IPs allowed on the Django admin URL, default allows all) and CADDY_TRUSTED_PROXIES (space-separated CIDR list of proxies whose X-Forwarded-For sets the client IP, default private_ranges). | str | no |  |
| st_docs_compose_template | Local path to the custom template to use for docs compose file. A custom template must include the y-provider service. | str | no | `docs/compose.yaml.j2` |
| st_docs_caddy_image | Image repository for the docs caddy reverse-proxy. | str | no | `docker.io/caddy` |
| st_docs_caddy_tag | The tag of the caddy docker image to use. See https://hub.docker.com/_/caddy/tags. | str | no | `2.11.7-alpine` |
| st_docs_docspec_image | Image repository for the docspec conversion service. | str | no | `ghcr.io/docspecio/api` |
| st_docs_docspec_tag | Tag of the docspec docker image to deploy. | str | no | `3.0.1` |
| st_docs_rollback_enabled | Whether or not to trigger the rollback tasks if the docs deployment fails. | bool | no | `False` |
| st_docs_frontend_logo_src | Local path to a custom logo file (svg) to mount over the docs frontend logo (/assets/icon-docs.svg). No validation is performed. Empty means use the image default. | str | no |  |
| st_docs_theme_customization_src | Local path to a custom theme customization JSON file to mount over the docs backend default theme. No validation is performed. Empty means use the image default. | str | no |  |
| st_docs_workers_enabled | Triggers the installation of the docs workers. | bool | no | `False` |
| st_docs_workers_dir | Remote path to the base directory for docs workers. | str | no | `/opt/docs/workers` |
| st_docs_workers_env_template | Local path to the custom template to use for docs workers env file. | str | no | `workers/env.j2` |
| st_docs_workers_env | Content of the default workers_env_template, not used if st_docs_workers_env_template is defined. | str | no | `{{ st_docs_backend_env }}` |
| st_docs_workers_secret_files | Secrets that the container reads from files. Each item has the key "env" (the variable name in upper case) and one of the keys "src" (local template) or "content" (inline value). The role writes the file "secrets/<env>" in the application directory. The role mounts the "secrets" directory read-only at /run/secrets. The role sets "<ENV>_FILE" in the compose environment. The "<ENV>_FILE" variable has priority over the same variable in the env content. The default value is the list of the backend. | list of `dict` | no | `{{ st_docs_backend_secret_files }}` |
| st_docs_workers_rollback_enabled | Whether or not to trigger the rollback tasks if the workers deployment fails. | bool | no | `False` |
| st_docs_workers_compose_template | Local path to the custom template to use for workers compose file. | str | no | `workers/compose.yaml.j2` |
| st_docs_yhub_enabled | Triggers the installation of the docs yhub collaboration server. | bool | no | `False` |
| st_docs_yhub_dir | Remote path to the base directory for the yhub app. | str | no | `/opt/docs/yhub` |
| st_docs_yhub_port | The host published port for the yhub collaboration server. | str | no | `50601` |
| st_docs_yhub_image | Image repository for the docs yhub collaboration server. | str | no | `docker.io/lasuite/impress-yhub` |
| st_docs_yhub_env_template | Local path to the custom template to use for yhub env file. | str | no | `yhub/env.j2` |
| st_docs_yhub_env | Content of the default yhub_env_template, not used if st_docs_yhub_env_template is defined. The keys REDIS and POSTGRES are required. Do not set PORT, because the compose file maps the container port 3002. | str | no |  |
| st_docs_yhub_secret_files | Secrets that the container reads from files. Each item has the key "env" (the variable name in upper case) and one of the keys "src" (local template) or "content" (inline value). The role writes the file "secrets/<env>" in the application directory. The role mounts the "secrets" directory read-only at /run/secrets. The role sets "<ENV>_FILE" in the compose environment. The "<ENV>_FILE" variable has priority over the same variable in the env content. | list of `dict` | no | `[]` |
| st_docs_yhub_compose_template | Local path to the custom template to use for yhub compose file. | str | no | `yhub/compose.yaml.j2` |
| st_docs_yhub_rollback_enabled | Whether or not to trigger the rollback tasks if the yhub deployment fails. | bool | no | `False` |
| st_docs_yhub_run_init_db | Whether to create or update the yhub database schema at each deployment. | bool | no | `True` |
| st_docs_yprovider_env_template | Local path to the custom template to use for y-provider env file. | str | no | `docs/yprovider_env.j2` |
| st_docs_yprovider_env | Content of the default yprovider_env_template, not used if st_docs_yprovider_env_template is defined. It is the env file of the y-provider conversion service in the docs unit. | str | no |  |
| st_docs_yprovider_legacy_cleanup_enabled | Whether to remove the legacy yprovider unit of docs v5 from the host at each deployment. | bool | no | `True` |
| st_docs_yprovider_legacy_dir | Remote path to the base directory of the legacy yprovider unit to remove. | str | no | `/opt/docs/yprovider` |
| st_docs_cadvisor_image | Image repository for the cadvisor container. | str | no | `ghcr.io/google/cadvisor` |
| st_docs_cadvisor_tag | Tag of the cadvisor docker image to deploy. | str | no | `v0.60.6` |
| st_docs_cadvisor_enabled | Triggers the installation of the cadvisor container, used to send metrics to a Prometheus compatible server and logs to a Loki server. | bool | no | `False` |
| st_docs_cadvisor_port | The host published port of the cadvisor container. | str | no | `127.0.0.1:50699` |

## Dependencies

None.

## Example Playbook

```yaml
- hosts: all
  tasks:
    - name: Importing role: suitenumerique.st.docs
      ansible.builtin.import_role:
        name: suitenumerique.st.docs
      vars:
```

## License

MIT

## Author and Project Information

La Suite territoriale @ Agence Nationale de la Cohésion des Territoires

Issues: [tracker](https://github.com/suitenumerique/st-ansible/issues)
<!-- END_ANSIBLE_DOCS -->
