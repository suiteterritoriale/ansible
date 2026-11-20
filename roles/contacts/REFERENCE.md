<!-- BEGIN_ANSIBLE_DOCS -->
# Ansible Role: suitenumerique.st.contacts
Version: 0.7.0
This role deploys the Contacts application from La Suite Territoriale on a rootless podman base on Debian systems.

Tags: suiteterritoriale, system

## Requirements

| Platform | Versions |
| -------- | -------- |
| Debian | trixie |

## Role Arguments

### Entrypoint: main

Installs and configures the Contacts application from La Suite Territoriale on Debian systems.

|Option|Description|Type|Required|Default|
|---|---|---|---|---|
| st_contacts_public_host | The public hostname used to access the contacts application. | str | no |  |
| st_contacts_uid | UID of the `contacts` user, used for the podman role. | int | no | `1111` |
| st_contacts_gid | GID of the `contacts` group, used for the podman role. | int | no | `{{ st_contacts_uid }}` |
| st_contacts_registries | Optional private container registries to login the `contacts` user onto. | list of `dict` | no |  |
| st_contacts_frontend_image | Image repository for the contacts frontend. | str | no | `ghcr.io/suitenumerique/contacts-frontend` |
| st_contacts_backend_image | Image repository for the contacts backend and workers. | str | no | `ghcr.io/suitenumerique/contacts-backend` |
| st_contacts_tag | Tag of the contacts images to deploy. Contacts has no release yet, so the default is the mutable `main` tag. Do not pin `main` by digest: the upstream CI deletes untagged images. | str | no | `main` |
| st_contacts_enabled | Triggers the installation of the contacts application. | bool | no | `False` |
| st_contacts_dir | Remote path to the base directory for contacts app. | str | no | `/opt/contacts/contacts` |
| st_contacts_port | The host published port for the contacts frontend. | str | no | `51100` |
| st_contacts_rollback_enabled | Whether or not to trigger the rollback tasks if the contacts deployment fails. | bool | no | `False` |
| st_contacts_compose_template | Local path to the custom template to use for contacts compose file. | str | no | `contacts/compose.yaml.j2` |
| st_contacts_frontend_env_template | Local path to the custom template to use for contacts frontend env file. | str | no | `contacts/frontend_env.j2` |
| st_contacts_frontend_env | Content of the default frontend_env_template, not used if st_contacts_frontend_env_template is defined. The frontend is a Caddy server. Set CONTACTS_FRONTEND_BACKEND_SERVER=contacts-backend:8000. The other keys are optional: DJANGO_ADMIN_URL, DJANGO_ADMIN_IP_ALLOWLIST and CONTACTS_FRONTEND_TRUSTED_PROXIES. | str | no |  |
| st_contacts_backend_env_template | Local path to the custom template to use for contacts backend env file. | str | no | `contacts/backend_env.j2` |
| st_contacts_backend_env | Content of the default backend_env_template, not used if st_contacts_backend_env_template is defined. | str | no |  |
| st_contacts_backend_secret_files | Secrets that the container reads from files. Each item has the key "env" (the variable name in upper case) and one of the keys "src" (local template) or "content" (inline value). The role writes the file "secrets/<env>" in the application directory. The role mounts the "secrets" directory read-only at /run/secrets. The role sets "<ENV>_FILE" in the compose environment. The "<ENV>_FILE" variable has priority over the same variable in the env content. | list of `dict` | no | `[]` |
| st_contacts_backend_run_migrations | Whether to run the database migrations on deploy. | bool | no | `True` |
| st_contacts_workers_enabled | Triggers the installation of the contacts workers. | bool | no | `False` |
| st_contacts_workers_dir | Remote path to the base directory for contacts workers. | str | no | `/opt/contacts/workers` |
| st_contacts_workers_env_template | Local path to the custom template to use for contacts workers env file. | str | no | `workers/env.j2` |
| st_contacts_workers_env | Content of the default workers_env_template, not used if st_contacts_workers_env_template is defined. | str | no | `{{ st_contacts_backend_env }}` |
| st_contacts_workers_secret_files | Secrets that the container reads from files. Each item has the key "env" (the variable name in upper case) and one of the keys "src" (local template) or "content" (inline value). The role writes the file "secrets/<env>" in the application directory. The role mounts the "secrets" directory read-only at /run/secrets. The role sets "<ENV>_FILE" in the compose environment. The "<ENV>_FILE" variable has priority over the same variable in the env content. The default value is the list of the backend. | list of `dict` | no | `{{ st_contacts_backend_secret_files }}` |
| st_contacts_workers_rollback_enabled | Whether or not to trigger the rollback tasks if the workers deployment fails. | bool | no | `False` |
| st_contacts_workers_compose_template | Local path to the custom template to use for workers compose file. | str | no | `workers/compose.yaml.j2` |
| st_contacts_cadvisor_enabled | Triggers the installation of the cadvisor container, a Prometheus-compliant containers monitoring tool. | bool | no | `False` |
| st_contacts_cadvisor_image | Image repository for the cadvisor container. | str | no | `ghcr.io/google/cadvisor` |
| st_contacts_cadvisor_tag | Tag of the cadvisor docker image to deploy. | str | no | `v0.60.6` |
| st_contacts_cadvisor_port | The host published port of the cadvisor container. | str | no | `127.0.0.1:51199` |

## Dependencies

None.

## Example Playbook

```yaml
- hosts: all
  tasks:
    - name: Importing role: suitenumerique.st.contacts
      ansible.builtin.import_role:
        name: suitenumerique.st.contacts
      vars:
```

## License

MIT

## Author and Project Information

La Suite territoriale @ Agence Nationale de la Cohésion des Territoires

Issues: [tracker](https://github.com/suitenumerique/st-ansible/issues)
<!-- END_ANSIBLE_DOCS -->
