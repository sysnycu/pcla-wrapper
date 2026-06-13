# Agents And Weights

PCLA agent selection is dynamic. The wrapper validates the requested name
against `PCLA/agents.json` during Init and imports the model only
during Reset.

## Naming

Use:

```text
<family>_<variant>[_seed]
```

Examples:

| Name | Registry selection |
| --- | --- |
| `plant2_plant2_0` | PlanT 2.0, seed 0 |
| `carl_plant_3` | CaRL family, PlanT variant, seed suffix `3` |
| `tfv5_alltowns` | TransFuser v5 all-towns variant |
| `tfv6_regnet` | TransFuser v6 RegNet variant |
| `neat_neat` | NEAT default variant |

The optional seed suffix must be numeric. The exact effect of a seed depends on
the registry config path used by that upstream agent.

## Registry

Each `agents.json` entry supplies:

- `agent`: Python entry point relative to the PCLA root.
- `config`: model configuration or checkpoint path relative to the PCLA root.

An unknown family or variant is rejected before importing a large model. The
error includes accepted name formats from the current registry.

## Weights

Weights must exist at the path expected by the selected registry entry. Common
locations are:

```text
PCLA/pcla_agents/*_pretrained/
PCLA/pcla_agents/plant/config/
PCLA/pcla_agents/plant/weights/
```

Download and validate the official PCLA archive from the repository root:

```bash
./scripts/download_pcla_pretrained.sh
```

The script resumes partial downloads, verifies SHA-256
`0d02c1aaf9ea81b892fef8815c1a8ab617c1906b89ee984ba8163332d659fa93`,
extracts without overwriting existing files, and validates the registry paths.
Set `PCLA_KEEP_PRETRAINED_ARCHIVE=1` to retain the downloaded ZIP.

The fixed PCLA base image supplies the Python/model environment. The weights
are excluded from Docker builds and mounted read-only:

```bash
docker run --rm --gpus all --network host \
  -v /host/maps:/mnt/map/xodr:ro \
  -v /host/output:/mnt/output \
  -v "$PWD/PCLA/pcla_agents:/opt/pcla-pretrained:ro" \
  pcla-wrapper
```

The image creates links for the official `*_pretrained` directories during
build. They point to the fixed runtime mount `/opt/pcla-pretrained`, so startup
does not write below `/app` and works with Docker's `--user` option.

PlanT also resolves its checkpoint directly through `PCLA_PRETRAINED_ROOT` if
the source-tree link is unavailable. A missing checkpoint error lists every
path checked by the agent.

LMDrive checkpoints in the archive are adapters for external Hugging Face base
models such as LLaVA, Vicuna, and LLaMA. SimLingo also loads its configured
vision/language base model through Transformers. Their first run therefore
needs network access or a populated Hugging Face cache in addition to this
archive. Model access terms and GPU memory requirements still apply.

## Rendering And Sensors

Sensor requirements differ by agent:

- Camera-based agents require rendering. The wrapper automatically disables
  `no_rendering_mode` after detecting a camera sensor.
- The owned server must not use NullRHI for camera agents.
- Agents using OpenDRIVE pseudo-sensors require a valid generated CARLA map.
- Sensor spawn failure is a reset precondition failure and partial sensors are
  cleaned automatically.

PCLA owns only sensors created for its current instance. The wrapper owns the
ego and observation-controlled actors.

### Camera Matrix

The following registry selections create camera sensors and require rendering:

- `tfv3_*`, `tfv4_*`, `tfv5_*`, and `tfv6_*`
- `neat_*`
- `lav_*`
- `lbc_*` and `wor_*`
- `lmdrive_*`
- `simlingo_simlingo`
- `if_if`

The following selections do not use camera input:

- `plant2_plant2_[0-2]` while `PLANT_VIZ` is empty
- `carl_carl_*`, `carl_carlv11`, and `carl_roach_*`
- `carl_plant*` while its YAML has `visualize: false`

PlanT adds one RGB camera only when `visualize: true`. PlanT 2 behaves the same
way when `PLANT_VIZ` is non-empty. These cameras are for visualization rather
than driving model input.

## Validation Scope

The automated suite validates registry selection, constructor arguments,
sensor ownership, route setup, and lifecycle behavior using fakes. Real GPU
inference, model checkpoints, and every registry variant are not covered by
those tests. Record verified agent/image/weight combinations separately in
deployment release notes.
