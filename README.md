# PCLA Wrapper

PISA AV service adapter for the [PCLA](https://github.com/MasoudJTehrani/PCLA)
multi-agent driving framework. The wrapper mirrors each PISA observation into a
CARLA shadow world, ticks CARLA once, and returns the selected PCLA agent's
throttle, brake, and steer command.

## Lifecycle

The server exposes the standard `pisa-api>=0.3.0` AV lifecycle:

- `Init`: validate configuration, optionally launch CARLA, and connect.
- `Reset`: load the scenario OpenDRIVE map, spawn ego, build a route, load the
  selected PCLA agent, process the initial observation, and return control.
- `Step`: synchronize ego and non-ego actors, tick once, then run PCLA.
- `ShouldQuit`: report route completion, PCLA failures, or owned CARLA process
  exits with a diagnostic message.
- `Stop`: idempotently clean PCLA-owned sensors and wrapper-owned actors while
  keeping the container-owned CARLA process available for the next Init/Reset.

The Python package is `pcla_wrapper`. The upstream PCLA fork is checked out as
the top-level `PCLA/` submodule.

## Runtime Contract

The Docker image uses:

- Ubuntu 24.04 as the final CARLA-compatible runtime.
- PCLA runtime copied from the pinned base:
  `sys511613/pcla@sha256:698fb44c2b9b3a142304f37761a8c1c05dd7cf0a2983736657980c577e72326d`
- Python 3.8.18
- PyTorch 2.2.0+cu121
- CUDA runtime 12.1
- CARLA server and Python API 0.9.16
- PISA API 0.3.1, pinned by `uv.lock`

The pinned PCLA stage provides the Conda, PyTorch, CUDA, and model/framework
dependencies. The top-level `pyproject.toml` manages only the wrapper API and
development tools.
The final image also installs PCLA's LMDrive-specific custom `timm`, LAVIS,
`torch-scatter`, and pinned `ftfy` requirements.
Upstream PCLA now documents Python 3.10, but this wrapper intentionally retains
the tested Python 3.8 runtime from its pinned PCLA image and CARLA wheel.
`requirements.txt` is retained as a legacy environment inventory and is not an
input to `uv sync`.

## Agents And Weights

Agent names use:

```text
<family>_<variant>[_seed]
```

Examples:

- `plant2_plant2_0`
- `carl_plant_3`
- `tfv5_alltowns`
- `tfv6_regnet`
- `neat_neat`

Names are validated against `PCLA/agents.json` before model import.
Weights and agent-specific configuration must exist at the paths referenced by
that registry, normally below `PCLA/pcla_agents/*_pretrained`.
The official archive is kept outside the image and mounted read-only because it
expands to more than 40 GiB. Build-time links point the upstream PCLA paths to
the fixed `/opt/pcla-pretrained` runtime mount.
Missing model files surface as an AV availability error.

The wrapper's fake-based suite validates the PlanT-compatible code path and
dynamic registry selection. It does not claim real GPU inference validation for
all PCLA agents.

## Configuration

Use [config_example.yaml](config_example.yaml). The canonical interface is flat:

```yaml
pcla_agent: carl_plant_3
pcla_root: /app/PCLA
route_xml_path: null
launch_carla_server: true
carla_connect_timeout_seconds: 30.0
retry_interval_seconds: 2.0
sync: true
no_rendering: false
sensor_warmup_ticks: 1
xodr_root: /mnt/map/xodr
reuse_generated_world: true
coordinate_y_sign: -1.0
yaw_sign: -1.0
steer_sign: -1.0
object_identity_mode: stateless
```

Legacy nested `pcla:` and `carla:` mappings are accepted for one compatibility
release. Conflicting flat and nested values are rejected.

Precedence, highest first:

1. `PCLA_AGENT`, `PCLA_ROUTE`, `CARLA_HOST`, `CARLA_PORT`, `CARLA_TIMEOUT`
2. Flat request config
3. Legacy nested request config
4. Built-in defaults

`coordinate_y_sign`, `yaw_sign`, and `steer_sign` are independent and must be
non-zero. PISA yaw and yaw rate are interpreted as radians.

`object_identity_mode` supports:

- `stateless`: recreate non-ego actors every frame.
- `index`: preserve actors by observation list index.
- `provided`: use `id`, `object_id`, `track_id`, `external_id`, or `name`.

Detailed references:

- [Documentation index](docs/README.md)
- [Configuration reference](docs/configuration.md)
- [Agents and weights](docs/agents.md)
- [Deployment](docs/deployment.md)
- [Lifecycle and ownership](docs/lifecycle.md)
- [Troubleshooting](docs/troubleshooting.md)

## CARLA Modes

Internal mode is the default. The wrapper starts `/app/carla_server.sh` and
writes logs below `<output_dir>/carla_server/`. The Docker image includes CARLA
0.9.16 at `/opt/carla`.

For an external server:

```yaml
launch_carla_server: false
```

Set `CARLA_HOST` and `CARLA_PORT` to the external endpoint. Only a process
launched by this wrapper is reused across Init/Reset cycles and exits with the
container.

## Build And Run

Initialize the upstream code first:

```bash
git submodule update --init --recursive
./scripts/download_pcla_pretrained.sh
docker build -t pcla-wrapper .
```

The download is resumable and verifies the official archive SHA-256 before
extracting it. Pretrained directories are excluded by `.dockerignore`, so
normal image rebuilds do not resend the weights to Docker.

Typical volumes:

```bash
docker run --rm --gpus all --network host \
  -e DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v "$HOME/.Xauthority":/home/carla/.Xauthority:ro \
  -v /path/to/xodr:/mnt/map/xodr:ro \
  -v /path/to/output:/mnt/output \
  -v "$PWD/PCLA/pcla_agents:/opt/pcla-pretrained:ro" \
  pcla-wrapper
```

This still launches CARLA inside the PCLA container. The X11 mounts only provide
the display authorization required by Unreal/Vulkan on supported NVIDIA hosts;
they do not connect to an external CARLA server.

The image contains build-time links from each official `*_pretrained` path to
`/opt/pcla-pretrained`. Startup therefore works with `--user` and does not need
write permission under `/app`.
PISA sends `output_dir`, `dt`, config, scenario, and observations through the AV
service; the default gRPC port is `50051`.

## Development

```bash
uv lock
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

The tests replace CARLA, PCLA, and model modules with fakes, so they do not
require a GPU, weights, or a running CARLA server.
