# Agents And Weights

PCLA agent selection is dynamic. The wrapper validates the requested name
against `PCLA-wrapper/PCLA/agents.json` during Init and imports the model only
during Reset.

## Naming

Use:

```text
<family>_<variant>[_seed]
```

Examples:

| Name | Registry selection |
| --- | --- |
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
PCLA-wrapper/PCLA/pcla_agents/*_pretrained/
PCLA-wrapper/PCLA/pcla_agents/plant/config/
PCLA-wrapper/PCLA/pcla_agents/plant/weights/
```

The fixed PCLA base image supplies its model environment. Additional or updated
weights can be baked into a derived image or mounted directly over the expected
directory:

```bash
docker run --rm --gpus all --network host \
  -v /host/maps:/mnt/map/xodr:ro \
  -v /host/output:/mnt/output \
  -v /host/plant-weights:/app/PCLA-wrapper/PCLA/pcla_agents/plant/weights:ro \
  pcla-wrapper
```

Check the selected `agents.json` entry before choosing a mount target. Mounting
the wrong directory can hide files included in the image.

## Rendering And Sensors

Sensor requirements differ by agent:

- Camera-based agents may require `no_rendering: false`.
- Agents using OpenDRIVE pseudo-sensors require a valid generated CARLA map.
- Sensor spawn failure is a reset precondition failure and partial sensors are
  cleaned automatically.

PCLA owns only sensors created for its current instance. The wrapper owns the
ego and observation-controlled actors.

## Validation Scope

The automated suite validates registry selection, constructor arguments,
sensor ownership, route setup, and lifecycle behavior using fakes. Real GPU
inference, model checkpoints, and every registry variant are not covered by
those tests. Record verified agent/image/weight combinations separately in
deployment release notes.
