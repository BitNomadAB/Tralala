# Running Tralala

The operator's checklist for a Docker install on your own machine or a private server: starting on
boot, where the data lives, backups and restoring a board, upgrading, rolling back, keeping the disk
in check, which connections leave the machine, and trusting the certificate of a private name.
[Installation.md](Installation.md) gets you to a running stack; this page keeps it running.

Commands below run from the directory that holds `docker-compose.yml`. API calls use a token with the
scope named in [API.md](API.md), created under **Settings → New access key**:

```bash
export TRALALA=https://tralala.example.com/api/v1
export TOKEN=<an API token>
```

## Start on boot

Both containers are `restart: unless-stopped`, so they come back whenever Docker does. Make sure
Docker itself starts with the machine:

- Linux: `sudo systemctl enable --now docker`
- Windows and macOS: Docker Desktop → Settings → General → **Start Docker Desktop when you sign in**

A container you stopped with `docker compose stop` stays stopped until you start it again.

## Where the data lives

Everything Tralala stores is in one directory, `/data` inside the backend container: the registry,
one database per board with its files, the backups, and the repository cache. By default that is the
named volume `tralala-data`. To keep it on a disk of your choice, set `TRALALA_DATA_PATH` in `.env`
to a directory on the host, which then becomes a bind mount:

```ini
TRALALA_DATA_PATH=/srv/tralala/data
```

The backend runs as the unprivileged user with uid 10001, so that user must own the directory:

```bash
sudo mkdir -p /srv/tralala/data
sudo chown -R 10001:10001 /srv/tralala/data
docker compose up -d
```

To move an existing install from the named volume to that directory, stop the stack, copy the volume
out and start again:

```bash
docker compose down
docker run --rm -v tralala-data:/from -v /srv/tralala/data:/to alpine sh -c "cp -a /from/. /to/"
sudo chown -R 10001:10001 /srv/tralala/data
docker compose up -d            # with TRALALA_DATA_PATH set in .env
```

The layout inside the directory is in [Installation.md](Installation.md#where-the-data-lives).

## Backups

The backend snapshots every board on a schedule with SQLite's online backup API, so a snapshot is a
complete, consistent database even while people work:

| Setting | Default | Meaning |
| --- | --- | --- |
| `TRALALA_BACKUP_INTERVAL_HOURS` | `24` | Hours between scheduled snapshots of each board |
| `TRALALA_BACKUP_KEEP` | `10` | Snapshots kept per board; the oldest go first |

Snapshots live in `<data>/backups/<board id>/` as `backup-<UTC time>.sqlite`, with a
`-attachments.zip` partner holding the board's files. A migration adds
`backup-<UTC time>-pre-migration.sqlite` before it changes a board's schema, and the registry gets the
same under `<data>/backups/registry/`.

Take a snapshot of one board now, and list what exists:

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" "$TRALALA/boards/<board id>/backups"
curl -s -H "Authorization: Bearer $TOKEN" "$TRALALA/boards/<board id>/backups"
```

To keep copies off the machine, copy `<data>/backups/` (each file is complete when it appears) and
the registry snapshots in it. Do not copy the live `*.sqlite` files of a running stack: a copy taken
mid-write may not open.

## Restoring a board from a backup

An administrator token (`boards:admin`) restores one board without touching any other:

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  "$TRALALA/boards/<board id>/backups/<backup name>/restore"
```

The snapshot is checked before anything changes (read only, integrity, schema), then the database and
its files are replaced and checked once more; the answer reports what was restored. Work done on the
board after the snapshot was taken is gone, so take a fresh snapshot first if you may want it back.

## Upgrading

```bash
git pull                         # or unpack the new release in place of the old one
docker compose up -d --build
docker compose ps                # backend and frontend "healthy"
```

The data directory is not touched by the upgrade itself. When the backend starts, it applies any new
schema revision to the registry and to every board, each one after a verified pre-migration snapshot.
A board whose migration fails is marked `migration_failed`, keeps its snapshot and refuses writes;
`POST /boards/<board id>/migrate` (`boards:admin`) retries it once the cause is fixed.

## Rolling back

To go back to the previous version after an upgrade that migrated the schema:

1. Stop the stack: `docker compose down`.
2. For the registry and every migrated board, put the pre-migration snapshot in place of the live
   file, keeping the newer file aside:

   ```bash
   cd /srv/tralala/data             # your data directory
   mv registry.sqlite registry.sqlite.after-upgrade
   cp backups/registry/backup-<UTC time>-pre-migration.sqlite registry.sqlite
   mv boards/<board id>/board.sqlite boards/<board id>/board.sqlite.after-upgrade
   cp backups/<board id>/backup-<UTC time>-pre-migration.sqlite boards/<board id>/board.sqlite
   sudo chown -R 10001:10001 .
   ```

   With the named volume, run the same commands inside a helper container:
   `docker run --rm -it -v tralala-data:/data alpine sh`, then `cd /data`.
3. Check out or unpack the previous version and start it: `docker compose up -d --build`.

Anything written between the upgrade and the rollback is in the `*.after-upgrade` files only.

## Disk housekeeping

| What | Where | What to do |
| --- | --- | --- |
| Board snapshots | `<data>/backups/<board id>/` | Kept to `TRALALA_BACKUP_KEEP`; lower it, or delete old pre-migration snapshots once an upgrade has proved itself |
| Repository cache | `<data>/repos/` | Mirrors and archives of linked repositories; a cache only. Safe to delete while the stack is stopped: the next run fetches again |
| Old images | Docker | `docker image prune` after an upgrade |
| Container logs | Docker | Bound them with Docker's `json-file` options `max-size` and `max-file` in the daemon configuration |

## Outbound connections

Tralala needs none. With a model on your own network and no linked repository it works with no
connection leaving the machine. The backend connects only to:

- the agent endpoints you configure (a model server, a gateway, an A2A agent);
- the hosts of linked repositories: `api.github.com` and `codeload.github.com` for a GitHub
  repository, and the hosts in `TRALALA_REPOSITORY_HOSTS` for a repository read through the mirror.

The web tier reaches out only for a certificate when `TRALALA_SITE_ADDRESS` is a public name (ACME).
There is no telemetry, no update check and no content delivery network: the browser loads everything
from your server.

## Trusting the certificate of a private name

For a name that no public certificate authority can check (`tralala.internal`, a name on a closed
network), Caddy issues the certificate from its own local authority, and browsers warn until that
authority is trusted. Copy its root certificate out of the web container:

```bash
docker compose cp frontend:/data/caddy/pki/authorities/local/root.crt ./tralala-root.crt
```

Then trust it on each machine that opens Tralala:

| System | Command |
| --- | --- |
| Windows (as administrator) | `certutil -addstore -f ROOT tralala-root.crt` |
| macOS | `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain tralala-root.crt` |
| Debian, Ubuntu | `sudo cp tralala-root.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates` |
| Firefox | Settings → Privacy & Security → Certificates → View Certificates → Authorities → Import |

The root stays valid for years and survives restarts, because it lives in the `tralala-caddy-data`
volume. Removing that volume creates a new authority, and every machine must trust the new root.
