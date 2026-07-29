# Source Development Image

This project can build a local server image from the checked-out source while
continuing to use the existing `deploy/` MySQL, Redis, data, and web containers.

## Architecture

The development overlay does not create a second server container.

`deploy/docker-compose.dev.yml` overrides the same service from
`deploy/docker-compose_all.yml`:

```text
Production mode:
  xiaozhi-esp32-server container
    -> ghcr.nju.edu.cn/xinnan-tech/xiaozhi-esp32-server:server_latest

Development mode:
  xiaozhi-esp32-server container
    -> xiaozhi-esp32-server:${XIAOZHI_DEV_TAG}
    -> built from local source with Dockerfile-server
```

The service name and container name remain unchanged:

```text
service:   xiaozhi-esp32-server
container: xiaozhi-esp32-server
```

Only the image source changes. This means production mode and development mode
are two ways to run the same container slot, not two containers running in
parallel.

The existing runtime dependencies are reused:

```text
deploy/data                     -> server config mount
deploy/models/.../model.pt      -> local model mount
xiaozhi-esp32-server-db         -> MySQL container
xiaozhi-esp32-server-redis      -> Redis container
xiaozhi-esp32-server-web        -> manager web/API container
```

When the server is restarted with `--no-deps`, MySQL, Redis, and the manager
container are not restarted.

## Build

```bash
export XIAOZHI_DEV_TAG="$(git rev-parse --short HEAD)-dev"
docker compose -f deploy/docker-compose_all.yml -f deploy/docker-compose.dev.yml build xiaozhi-esp32-server
```

If `ghcr.io` is slow or unavailable, set a mirror/base image explicitly:

```bash
export XIAOZHI_SERVER_BASE_IMAGE="ghcr.io/xinnan-tech/xiaozhi-esp32-server:server-base"
```

## Run Only The Server

```bash
docker compose -f deploy/docker-compose_all.yml -f deploy/docker-compose.dev.yml up -d --no-deps --force-recreate xiaozhi-esp32-server
```

The container logs print `XIAOZHI_SOURCE_REVISION`, so you can confirm which
source build is running.

## Daily Development Workflow

1. Edit code under `main/xiaozhi-server/`.
2. Rebuild the source image:

```bash
export XIAOZHI_DEV_TAG="$(git rev-parse --short HEAD)-dev"
docker compose -f deploy/docker-compose_all.yml -f deploy/docker-compose.dev.yml build xiaozhi-esp32-server
```

3. Replace only the server container:

```bash
docker compose -f deploy/docker-compose_all.yml -f deploy/docker-compose.dev.yml up -d --no-deps --force-recreate xiaozhi-esp32-server
```

4. Check startup logs:

```bash
docker logs xiaozhi-esp32-server --tail 100
```

## Verify

```bash
docker image inspect "xiaozhi-esp32-server:${XIAOZHI_DEV_TAG}" \
  --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'

docker logs xiaozhi-esp32-server --tail 80
```

## Roll Back

Run the original compose file without the development overlay:

```bash
docker compose -f deploy/docker-compose_all.yml up -d --no-deps --force-recreate xiaozhi-esp32-server
```

## Handoff Notes

- Do not run `git add deploy/`. The `deploy/` directory contains local runtime
  state such as database files, uploaded files, local config, and model files.
- If source-image workflow changes are ready to commit, add only the safe
  source-build files, for example `Dockerfile-server`,
  `deploy/docker-compose.dev.yml`, `.dockerignore`, and this document. Do not
  include runtime state under `deploy/`.
- `.dockerignore` excludes `deploy/` from the Docker build context. Keep this
  rule, otherwise local runtime data can be sent into Docker builds.
- `Dockerfile-server` copies only `main/xiaozhi-server/`, so manager/web/mobile
  code changes are not included in the server image.
- `XIAOZHI_SOURCE_REVISION` is printed during server startup. If logs do not
  show the expected value, the container is probably not running the expected
  development image.
