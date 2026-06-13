# Deployment

## Image Contract

The provided Dockerfile uses:

- Ubuntu 24.04 as the final CARLA-compatible runtime.
- PCLA Conda/CUDA runtime copied from a base image pinned by digest.
- Python 3.8.18.
- PyTorch 2.2.0+cu121 and CUDA 12.1 from the PCLA base.
- CARLA server and Python API 0.9.16.
- PISA API pinned by `uv.lock`.
- LMDrive custom vision encoder/LAVIS packages, `torch-scatter`, and
  `ftfy==6.1.1`.

Upstream PCLA changed its environment specification to Python 3.10 in March
2026. This wrapper keeps the pinned, tested Python 3.8 environment because its
runtime base and bundled CARLA API wheel use CPython 3.8.

Initialize the submodule before building:

```bash
git submodule update --init --recursive
./scripts/download_pcla_pretrained.sh
docker build -t pcla-wrapper .
```

The pretrained archive expands to more than 40 GiB and is excluded from the
Docker build context. Mount it at runtime instead of baking it into the image.
The image creates the required links at build time; the entrypoint does not
need write permission below `/app`.

## Required Volumes

| Container path | Purpose |
| --- | --- |
| `/mnt/map/xodr` | `<ScenarioPack.map_name>.xodr` files. |
| `/mnt/output` | PISA output and CARLA server logs. |
| `/opt/pcla-pretrained` | Host `pcla_agents` directory containing official `*_pretrained` folders. |

The request output directory should be under the mounted output path. Generated
routes are isolated below each reset output directory.

PISA commonly sends `/mnt/output` in Init and a case name such as `concrete` in
Reset. The wrapper resolves that case to `/mnt/output/concrete`; it does not
write relative paths below `/app`.

The Docker image also uses `/mnt/output/.carla-home` for CARLA navigation cache.
The output volume must therefore be writable by the container process.
When using `--user`, either make that volume writable by the selected UID or
set `CARLA_HOME` to another writable path. `XDG_CACHE_HOME` follows
`CARLA_HOME`; `PCLA_XDG_CACHE_HOME` can override it separately.

## Internal CARLA

The default config launches `/app/carla_server.sh`:

```yaml
launch_carla_server: true
carla_server_script: /app/carla_server.sh
```

The launcher uses `-RenderOffScreen`, low quality, and GPU rendering. Run the
container with `--gpus all`. It does not use `-nullrhi` because NullRHI disables
camera sensor production and can destabilize generated OpenDRIVE worlds.
The Ubuntu 24 final stage follows the working `carla-wrapper` and
`carla-agent-wrapper` runtime pattern. The image requests all NVIDIA driver
capabilities, matching the established
CARLA wrapper runtime. Graphics/display support is required by CARLA's Vulkan
initialization on some driver stacks even with `-RenderOffScreen`. It supplies
the NVIDIA Vulkan ICD manifest and EGL loader missing from the PCLA base image.
Because Unreal refuses root execution, the launcher drops only the CARLA child
to the image's `carla` user (`1000:1000`) by default. Override `CARLA_RUN_UID`
and `CARLA_RUN_GID` when the mounted cache uses a different runtime identity.

CARLA logs are written to:

```text
<InitRequest.output_dir>/carla_server/stdout.log
<InitRequest.output_dir>/carla_server/stderr.log
```

The owned CARLA process is started once per container and reused across
Init/Reset cycles. Stop clears the current PCLA agent, sensors, vehicles, and
other dynamic actors without restarting CARLA. Container shutdown terminates
the server.

Example:

```bash
docker run --rm --gpus all --network host \
  -e DISPLAY \
  -e PORT=50051 \
  -e CARLA_PORT=2000 \
  -e CARLA_HOME=/mnt/output/.carla-home \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v "$HOME/.Xauthority":/home/carla/.Xauthority:ro \
  -v /host/maps:/mnt/map/xodr:ro \
  -v /host/output:/mnt/output \
  -v "$PWD/PCLA/pcla_agents:/opt/pcla-pretrained:ro" \
  pcla-wrapper
```

The launcher automatically detects `/home/carla/.Xauthority` and the
`/root/.Xauthority` path used by existing repository `justfile` commands when
`XAUTHORITY` is unset. Mounting X11 is the tested portable contract used by the
other CARLA wrappers here. CARLA still runs inside this container; X11 is only
used by Unreal/Vulkan initialization.

Set `CARLA_QUALITY_LEVEL=Epic` only when an agent requires higher visual
quality. `CARLA_NULLRHI=1` is reserved for sensorless agents and ignores the
quality setting because CARLA 0.9.16 crashes when both arguments are supplied.

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
