# Deployment

## Image Contract

The provided Dockerfile uses:

- PCLA base image pinned by digest.
- Python 3.8.18.
- PyTorch 2.2.0+cu121 and CUDA 12.1 from the PCLA base.
- CARLA server and Python API 0.9.16.
- PISA API pinned by `uv.lock`.

Initialize the submodule before building:

```bash
git submodule update --init --recursive
docker build -t pcla-wrapper .
```

## Required Volumes

| Container path | Purpose |
| --- | --- |
| `/mnt/map/xodr` | `<ScenarioPack.map_name>.xodr` files. |
| `/mnt/output` | PISA output and CARLA server logs. |
| Agent-specific PCLA paths | Optional external weights/checkpoints. |

The request output directory should be under the mounted output path. Generated
routes are isolated below each reset output directory.

## Internal CARLA

The default config launches `/app/carla_server.sh`:

```yaml
launch_carla_server: true
carla_server_script: /app/carla_server.sh
```

CARLA logs are written to:

```text
<InitRequest.output_dir>/carla_server/stdout.log
<InitRequest.output_dir>/carla_server/stderr.log
```

Example:

```bash
docker run --rm --gpus all --network host \
  -e PORT=50051 \
  -e CARLA_PORT=2000 \
  -v /host/maps:/mnt/map/xodr:ro \
  -v /host/output:/mnt/output \
  pcla-wrapper
```

## External CARLA

Disable process launch and point the wrapper to an existing compatible server:

```yaml
launch_carla_server: false
```

```bash
docker run --rm --gpus all --network host \
  -e CARLA_HOST=127.0.0.1 \
  -e CARLA_PORT=2000 \
  -e CARLA_TIMEOUT=120 \
  -v /host/maps:/mnt/map/xodr:ro \
  -v /host/output:/mnt/output \
  pcla-wrapper
```

The external server must be reachable from the container and use a CARLA
version compatible with Python API 0.9.16. Stop never terminates an external
process.

## Ports

- `PORT`: PISA AV gRPC service port, default `50051`.
- `CARLA_PORT`: CARLA RPC port, default `2000`.
- `CARLA_TM_PORT`: TrafficManager port, default `8000`.

Only one process can bind each host port. With host networking, choose unique
ports when running wrappers in parallel.

## Development Validation

```bash
uv lock
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run pytest
docker build .
```

The unit tests do not require CARLA, GPU access, or model weights.
