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
- `Stop`: idempotently clean PCLA-owned sensors, wrapper-owned actors, and an
  owned CARLA process.

The Python package is `pcla_wrapper`. `PCLA-wrapper/` only contains legacy
entry-point shims and the upstream PCLA submodule.

## Runtime Contract

The Docker image is based on:

- PCLA base:
  `sys511613/pcla@sha256:698fb44c2b9b3a142304f37761a8c1c05dd7cf0a2983736657980c577e72326d`
- Python 3.8.18
- PyTorch 2.2.0+cu121
- CUDA runtime 12.1
- CARLA server and Python API 0.9.16
- PISA API 0.3.1, pinned by `uv.lock`

The PCLA base image provides model/framework dependencies. The top-level
`pyproject.toml` manages only the wrapper API and development tools.
`requirements.txt` is retained as a legacy environment inventory and is not an
input to `uv sync`.

## Agents And Weights

Agent names use:

```text
<family>_<variant>[_seed]
```

Examples:

- `carl_plant_3`
- `tfv5_alltowns`
- `tfv6_regnet`
- `neat_neat`

Names are validated against `PCLA-wrapper/PCLA/agents.json` before model import.
Weights and agent-specific configuration must exist at the paths referenced by
that registry, normally below `PCLA-wrapper/PCLA/pcla_agents/*_pretrained`.
Large weights may be supplied by the base image or mounted into those paths.
Missing model files surface as an AV availability error.

The wrapper's fake-based suite validates the PlanT-compatible code path and
dynamic registry selection. It does not claim real GPU inference validation for
all PCLA agents.

## Configuration

Use [config_example.yaml](config_example.yaml). The canonical interface is flat:

```yaml
pcla_agent: carl_plant_3
pcla_root: /app/PCLA-wrapper/PCLA
route_xml_path: null
launch_carla_server: true
carla_connect_timeout_seconds: 30.0
retry_interval_seconds: 2.0
sync: true
no_rendering: true
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
launched by this wrapper is terminated by `Stop`.

## Build And Run

Initialize the upstream code first:

```bash
git submodule update --init --recursive
docker build -t pcla-wrapper .
```

Typical volumes:

```bash
docker run --rm --gpus all --network host \
  -v /path/to/xodr:/mnt/map/xodr:ro \
  -v /path/to/output:/mnt/output \
  -v /path/to/weights:/app/PCLA-wrapper/PCLA/pcla_agents/plant/weights:ro \
  pcla-wrapper
```

The exact weights mount target depends on the selected entry in `agents.json`.
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
