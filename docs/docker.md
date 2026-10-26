# Docker operations

## First start

Use the image-based [docker-compose.yml](../docker-compose.yml) or the identical README example. Docker with the Compose plugin is sufficient; no source compilation, Node or Python installation is required on the host.

```bash
git clone https://github.com/lucas-lepajollec/sillage.git
cd sillage
```

Optional `.env`:

```dotenv
MEDIA_PATH=/srv/media
PUID=1000
PGID=1000
```

Replace the example path and UID/GID with your host library and owner. These values configure Compose substitutions; settings remain in `./config`.

```bash
docker compose up -d
docker compose ps
docker compose logs --tail=80 sillage
```

Open `http://<your-server-ip>:5775`. Configure a provider and test one selected episode first. The image healthcheck calls `/api/health`; it proves the server responds, not media permissions or provider quality.

## Permissions and mounts

The worker defaults to UID/GID 1000. The entrypoint runs briefly as root, creates/owns the config directory, then switches to PUID/PGID before starting FastAPI. It never recursively changes ownership of the media library.

The mounted media directory needs read permission for videos/subtitles and write permission on parent folders for sidecars. Fix host ACLs or group membership if export fails. Do not work around permissions by running the worker as root. When changing UID/GID on an existing config, adjust that config's ownership explicitly on the host first. An advanced `user: "UID:GID"` override is possible when directories are already writable.

The media directory is intentionally mounted read/write for exports; MKVs are never written by the application. Keep host administrators and filesystem writers trusted. Docker socket, privileged mode, host networking and GPU access are not required.

## Network access

The recommended `5775:5775` mapping publishes on the Docker host's interfaces. Use a trusted LAN/VPN and firewall. Change the host side of the mapping if the port is taken.

For loopback-only access, edit the mapping to:

```yaml
ports:
  - "127.0.0.1:5775:5775"
```

For an access key, create an ignored `docker-compose.override.yml`:

```yaml
services:
  sillage:
    environment:
      ACCESS_KEY: ${ACCESS_KEY:?Set ACCESS_KEY in your private .env}
```

Choose the key privately in `.env`, restart with `docker compose up -d`, and enter it in the web UI. Do not post that file. This is shared-key access, not user accounts or rate-limited identity management.

For a local reverse proxy, add its hostname through `ALLOWED_HOSTS` in the override and terminate HTTPS at the proxy. Preserve the real Host header; do not disable origin checks. Optional proxy-related settings are not required for a normal LAN start.

For Ollama on another machine, configure its reachable LAN URL in the UI. Container `localhost` is the container itself. To reach the Docker host, optionally add `extra_hosts: ["host.docker.internal:host-gateway"]` in a private override. Sillage does not install models or reconfigure your Ollama firewall.

## Update

Record the previous image digest and back up config before updating:

```bash
docker inspect --format '{{.Image}}' "$(docker compose ps -q sillage)"
docker compose pull
docker compose up -d
docker compose ps
```

If using a clone, run `git pull --ff-only` first to obtain updated Compose/documentation. Pulling Git alone does not refresh `latest`; run `docker compose pull` or `docker compose up -d --pull always`. Version tags (for example `0.1.0`) and full `sha-<commit>` tags provide recoverable references; `latest` follows accepted main builds.

## Backup and restore

1. Stop the service with `docker compose stop sillage`.
2. Copy the complete `config/` directory to protected storage. It includes SQLite/WAL state, checkpoints and `secret.key`; the key and database must stay together.
3. Restart with `docker compose start sillage`.

For a restore, stop the service, restore the complete directory, verify ownership and start it again. Keep backups private: they contain credentials and subtitle text. No automated external backup service is configured.

## Rollback and uninstall

Stop the service. Change the image line to the previous recorded digest or version. If a future release migrates state incompatibly, restore its matching pre-update config backup too, then run `docker compose up -d`. Do not assume old code can read a newer database.

`docker compose down` removes containers/network while retaining bind-mounted config and media. Removing config is a separate destructive action; do it only after a verified backup. The app never manages deletion of your media files.

## Build from source

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

The build override is deliberately separate from the recommended pull-only file. The final container contains the compiled frontend and backend. Keep local `.env`, config, private agent notes and media out of the build context.

## Troubleshooting

- **Connection refused:** inspect `docker compose ps` and logs; check the chosen host port and firewall.
- **Empty library:** set MEDIA_PATH to the actual host directory; browse `/media` in the app. No automatic whole-disk index is built.
- **Export denied:** inspect parent-directory permissions for PUID/PGID; do not change all library ownership automatically.
- **Output exists:** move the previous result yourself after checking it; Sillage refuses automatic replacement.
- **Provider fails:** verify endpoint/model/key in the UI. Use a reachable LAN address for a remote Ollama instance.
- **Interrupted job:** use Reprendre. Validated batches remain checkpointed; changing translation-affecting provider settings requires a new job.
- **ASS review:** unsupported geometry/karaoke/animation is preserved and warned, not silently discarded.
- **Sync refusal:** keep source timings or choose an explicit manual offset. A refusal is preferable to publishing an uncertain correction.
