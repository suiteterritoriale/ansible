# Upgrade from Docs v5 to Docs v6

Docs v6 replaces the collaboration server. The content of a document no longer lives in the S3 bucket. It
lives in the new `yhub` unit. An instance that upgrades without the data migration opens every document
empty. Read this page before the upgrade.

## What Changes

- A new unit, `yhub` (`/opt/docs/yhub`, port `st_docs_yhub_port`), replaces the `yprovider` unit.
- The y-provider is only a conversion service. It runs in the core unit, with no published port.
- Yhub needs its own PostgreSQL database and a durable Redis 6.2 or later, or Valkey.
- The backend and yhub authenticate each other with two RSA keys. `COLLABORATION_SERVER_SECRET` is removed.
- The role removes the legacy `yprovider` unit from the hosts. It frees the port `50601`.
- The documents must move from the bucket to yhub. The command `migrate_documents` does it.

## Prepare

Do these steps before the deployment:

1. Create an empty PostgreSQL database for yhub.
2. Prepare a durable Redis or Valkey for yhub. It is not the Django cache.
3. Enable the versioning of the S3 bucket.
4. Create S3 credentials with read-only access to the bucket. The credentials need `s3:ListBucket` and
   `s3:GetObject`. For a strict policy, add `s3:ListBucketVersions` and `s3:GetObjectVersion`: the backfill
   lists the object versions and reads each object by version. On MinIO, `s3:GetObject` alone fails with
   `AccessDenied` on the version list, while `s3:ListBucket` and `s3:GetObject` work, because MinIO does
   not enforce the version permissions. A provider with a strict policy model, for example AWS S3, needs
   `s3:ListBucketVersions` and `s3:GetObjectVersion` for the version history.
5. Open the port `50601` from the core hosts and from the workers hosts to the yhub hosts.
6. Plan a maintenance window.

## Variant with st-cli

1. With the `hashi_vault` backend only, run `st-cli generate-keypairs docs <env>` and store the two keys in
   the vault. Create the entries `POSTGRES`, `REDIS` and `LEGACY_S3_SECRET_ACCESS_KEY` too. All of them
   must exist in OpenBao before the deployment.
2. Run `st-cli upgrade`. Bootstrap the yhub unit in this run: do not answer "bootstrap later".
   `st-cli deploy` and `st-cli reset` refuse Docs until the yhub unit exists and the docs unit names it
   (`CADDY_YHUB_ENDPOINTS` and `YHUB_API_BASE_URL` are not empty). To clear the gate, run
   `st-cli bootstrap docs <env>` and answer "bootstrap now" (or the external answer) for yhub.
   A standalone `st-cli bootstrap docs <env> -c yhub` does not wire the docs unit. Answer the yhub questions. Set
   `SOFT_MIGRATION` to yes and give the `LEGACY_S3_*` values.
3. Before the deployment, do only the manual steps that are not marked "After". Delete the lines
   `COLLABORATION_SERVER_SECRET`, `COLLABORATION_API_URL` and `CADDY_YPROVIDER_ENDPOINTS`. With
   ansible-vault, remove `vault_collaboration_server_secret` with `st-cli secrets docs <env> -c docs`.
   The old comment lines above `Y_PROVIDER_API_BASE_URL` in `st_docs_backend_env` speak of yprovider hosts.
   St-cli never deletes a line, so you can delete this comment. The URL now points at the converter of
   the core unit.
   Commit the result. Keep `docs/<env>/yprovider/` and its entry in `.st-cli.yml` until the first
   successful deployment, because its play removes the old unit from the hosts.
4. Run `st-cli deploy docs <env>`. The order is: legacy cleanup, core with `migrate`, yhub with `init-db`,
   workers. After the first successful deployment, delete the directory `docs/<env>/yprovider/` and its
   entry in `.st-cli.yml`: its play has then removed the old unit from the hosts.
5. Migrate the documents (see [Migrate the Documents](#migrate-the-documents)).
6. Do the steps marked "After" in [After the Migration](#after-the-migration).

## Variant with the Role Only

1. Create the two keys:

   ```bash
   openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out backend.pem
   openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out yhub.pem
   ```

   Store them in your vault. Both keys must be PKCS#8 PEM. Recent OpenSSL versions write this format.

2. Set the variables of the core unit:

   ```yaml
   st_docs_tag: v6.1.0
   st_docs_backend_secret_files:
     - env: JWT_PRIVATE_KEY
       content: "{{ vault_jwt_private_key }}"
   st_docs_backend_env: |
     # Add these lines, and delete COLLABORATION_SERVER_SECRET and COLLABORATION_API_URL.
     COLLABORATION_WS_URL=wss://docs.example.com/collaboration/ws/v1/docs
     Y_PROVIDER_API_BASE_URL=http://y-provider:4444/api/
     YHUB_API_BASE_URL=http://yhub1.example.com:50601
     Y_PROVIDER_API_KEY={{ vault_y_provider_api_key }}
   st_docs_caddy_env: |
     # Replace CADDY_YPROVIDER_ENDPOINTS with this line.
     CADDY_YHUB_ENDPOINTS=yhub1.example.com:50601
   st_docs_yprovider_env: |
     COLLABORATION_BACKEND_BASE_URL=https://docs.example.com
   ```

   Delete `COLLABORATION_SERVER_SECRET` and `Y_PROVIDER_API_KEY` from the former y-provider env. The backend
   keeps `Y_PROVIDER_API_KEY`. The `st_docs_yprovider_env` variable
   now configures the conversion service in the core unit.

3. Set the variables of the yhub unit on the yhub hosts:

   ```yaml
   st_docs_yhub_enabled: true
   st_docs_yhub_secret_files:
     - env: YHUB_JWT_PRIVATE_KEY
       content: "{{ vault_yhub_jwt_private_key }}"
   st_docs_yhub_env: |
     REDIS=redis://valkey.example.com:6379/0
     POSTGRES=postgres://yhub:{{ vault_yhub_db_password }}@db.example.com:5432/yhub
     COLLABORATION_BACKEND_BASE_URL=https://docs.example.com
     COLLABORATION_SERVER_ORIGIN=https://docs.example.com
     Y_PROVIDER_API_KEY={{ vault_y_provider_api_key }}
     SOFT_MIGRATION=true
     LEGACY_S3_ENDPOINT_URL=https://s3.example.com
     LEGACY_S3_ACCESS_KEY_ID=<read-only access key id>
     LEGACY_S3_SECRET_ACCESS_KEY={{ vault_legacy_s3_secret_access_key }}
     LEGACY_S3_BUCKET_NAME=docs-media-storage
   ```

   Remove the variables `st_docs_yprovider_enabled`, `st_docs_yprovider_dir`, `st_docs_yprovider_port`,
   `st_docs_yprovider_compose_template` and `st_docs_yprovider_rollback_enabled`. The role does not know
   them any more.

4. Deploy the hosts. The role stops with an assertion before it deploys a unit when a setting of that unit
   is missing: `CADDY_YHUB_ENDPOINTS`, `YHUB_API_BASE_URL`, `JWT_PRIVATE_KEY`, `POSTGRES` or `REDIS`. The
   role does these tasks in this order: remove the legacy `yprovider` unit, deploy
   the core unit (with the Django migrations), deploy the yhub unit (with `init-db`), deploy the workers.
   If you use a custom `st_docs_compose_template`, add the `y-provider` service and the `yprovider_env`
   file to it first.

   The backend of Docs v6 needs about one minute after the container start before it answers. A request
   in this window gets HTTP 502 from the proxy.

## Migrate the Documents

Do not let users in before `SOFT_MIGRATION=true` is active on yhub. With it, yhub seeds a document from
its legacy S3 object when someone opens it first. A document that nobody opens stays in S3. The backfill
moves them all.

Run the commands with `st-cli`:

```bash
st-cli oneoff docs <env> -- python manage.py migrate_documents --dry-run
st-cli oneoff docs <env> -- python manage.py migrate_documents
st-cli oneoff docs <env> -- python manage.py migrate_documents --retry-failed
```

Without `st-cli`, run the same `python manage.py migrate_documents` command in a backend container as the
`docs` user (`podman-compose run --rm backend ...` in `/opt/docs/docs`).

The command `migrate_documents` works only while `SOFT_MIGRATION=true`, because yhub has no legacy S3
client when the setting is off. Do not run `migrate_documents` (also not with `--document-id`) after you
set `SOFT_MIGRATION=false`. Yhub then answers 503 "Legacy store is not configured", the command still
exits with code 0, and the row of a document that was `ok` becomes `failed`.

Run `migrate_documents` once. Then run `migrate_documents --retry-failed` until no document fails.
The command exits with code 0 also when documents fail. Read the summary that it prints, for example
`Migrated 29 documents in 1s (25.2/s): empty=1, ok=28`. Run `--retry-failed` until the failed count is 0.
A document with no content gets the status `empty`. A document that a user opened before the run is
already seeded, so the run counts fewer `ok` documents than the total.

`--dry-run` counts every document, also a document that is already migrated and a document with no
content.

The command records the result of each document in the database, so you can run it again at any time.
These options bound a run:

| Option | Effect |
|--------|--------|
| `--dry-run` | Count the documents to migrate and call nothing |
| `--retry-failed` | Hand over again the documents that a previous run could not migrate |
| `--limit` | Stop after this number of documents (`0` means all) |
| `--concurrency` | Number of documents that migrate at the same time (default `2`) |
| `--rate` | Maximum number of documents per second (`0` means no limit) |
| `--document-id` | Migrate this one document, whatever a previous run recorded |

## Effect on API Consumers

Before the backfill ends, the first read of a document that is not migrated depends on the settings of
yhub:

- With correct `LEGACY_S3_*` values and `SOFT_MIGRATION=true`, the first read migrates the document (lazy
  migration). `formatted-content/` returns HTTP 200.
- With wrong or missing `LEGACY_S3_*` credentials, `formatted-content/` returns HTTP 500
  `{"error":"Failed to get document content"}`. Yhub answers 503 "Legacy document store is unavailable".
- A document that has no content at all returns `content: null`, in Docs v5 and in Docs v6.

Compare Docs v5.6.1 and Docs v6.1.0 on 33 test documents after the migration:

- `formatted-content/` in html and json is byte-identical. The markdown output differs only by an escaped
  `<` (`\<`). The test did not compare content that users edit later with the Docs v6 editor (BlockNote 0.57).
- `children/` keeps the same keys and pagination.
- In the `abilities` object, `can_edit`, `content_patch`, `content_retrieve`, `versions_destroy` and
  `versions_retrieve` are gone. `mention` is new.
- `updated_at` changes for a document that the lazy migration handles, because yhub then notifies the
  backend. A document that the backfill migrates keeps its `updated_at`. A consumer that caches on
  `updated_at` fetches these documents one more time.

The endpoints `formatted-content/` and `children/` keep their URLs. Docs v6 makes these other changes
for API consumers:

- The endpoints `documents/{id}/content/`, `documents/{id}/versions/` and `documents/{id}/can-edit/` are
  removed. Stop calling them.
- The JWKS of the resource server moves from `/api/v1.0/jwks` to `/external_api/v1.0/jwks`. Update the
  JWKS URI that you declare to your service providers. `/api/v1.0/jwks` now publishes the public key of
  the backend for yhub and the y-provider.
- Since Docs v6.0.2, the actions of the resource server are denied unless the `EXTERNAL_API` setting lists
  them.
- Docs v6.1.0 does not use the `easy_thumbnails` tables any more. You can keep them or drop them (see the
  upstream `UPGRADE.md`).

### Throttle

The anonymous throttle of the documents API is the same in Docs v5 and Docs v6. The setting is
`API_DOCUMENT_THROTTLE_RATE`, and the default is `80/minute`. For an anonymous request, the limit applies
per client address. The throttle skips the calls that carry the `Y_PROVIDER_API_KEY` of yhub.

In Docs v6, `formatted-content/` answers in 0.1 to 0.7 s, where Docs v5 took 3 to 5 s. An application that
reads many documents through the API one after the other now reaches the limit and gets HTTP 429. An
application that obeys `Retry-After` only becomes slower. An application with no 429 handling fails.

For an instance that serves such an application, add `API_DOCUMENT_THROTTLE_RATE=<rate>`, for example
`600/minute`, to `st_docs_backend_env`. Or add a pause or a 429 handling in the application.

## After the Migration

When the backfill covers all documents:

1. Set `SOFT_MIGRATION=false` and delete the `LEGACY_S3_*` lines in `st_docs_yhub_env`.
2. Deploy the yhub unit again. With `st-cli`, run `st-cli deploy docs <env> -c yhub`.

If you set `SOFT_MIGRATION=false` too early, nothing is lost. But an unmigrated document then opens
empty.

## What to Keep in the Bucket

Keep the bucket versioning and the `<document-id>/file` objects with all their versions. Yhub reads them
for the lazy seed and for the backfill, which replays the full history of each document. They are the only
record of the documents before Docs v6. Nobody can recover them after a deletion. The attachments under
`<document-id>/attachments/` stay in use by the backend.
