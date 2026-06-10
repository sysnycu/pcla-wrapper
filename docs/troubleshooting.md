# Troubleshooting

## Init Times Out Connecting To CARLA

Check:

- `launch_carla_server` matches the intended ownership mode.
- `CARLA_HOST` and `CARLA_PORT` point to the correct endpoint.
- no other process occupies the selected CARLA port.
- `<output_dir>/carla_server/stderr.log` for internal-server failures.
- `carla_connect_timeout_seconds` is long enough for the host.

The normal RPC timeout is restored after every short connection attempt.

## OpenDRIVE Map Not Found

Reset resolves:

```text
<xodr_root>/<ScenarioPack.map_name>.xodr
```

Verify the filename, case, mount path, and read permission. The wrapper does not
fall back to the current CARLA world when the requested map is unavailable.

## Route Generation Fails

Verify:

- the initial observation contains the ego state,
- the scenario has an ego goal position,
- start and goal project onto the generated CARLA map,
- the route planner returns at least two waypoints,
- the reset output directory is writable.

To bypass generation, provide a readable `route_xml_path`.

## Unknown Agent

Agent names must use `<family>_<variant>[_seed]`. Inspect:

```bash
python -m json.tool PCLA-wrapper/PCLA/agents.json
```

The optional seed must be numeric. Do not infer a variant from a directory name;
use the registry keys.

## Missing Weights Or Python Dependencies

Inspect the selected `agents.json` entry and verify both its `agent` and
`config` paths inside the container. Also check whether a volume mount hides
files supplied by the image.

Model dependency or checkpoint failures are reported as `AvUnavailable`.
Explicit model loading timeouts are reported as `AvTimeout`.

## Sensors Do Not Produce Data

For camera agents, try:

```yaml
no_rendering: false
```

Also verify GPU availability, CARLA rendering support, sensor blueprint
availability, and that the agent's sensor specification is compatible with
CARLA 0.9.16.

## Non-Ego Actors Swap Identity

Use:

```yaml
object_identity_mode: provided
```

and include one stable attribute per non-ego object: `id`, `object_id`,
`track_id`, `external_id`, or `name`. Use `index` only when ordering is stable.
The default `stateless` mode avoids identity swaps by rebuilding actors.

## PCLA Returns No Action

With the default:

```yaml
action_none_timeout_seconds: 0.0
```

the wrapper raises an immediate precondition failure. Set a small positive
timeout only for agents that legitimately need several polls after the CARLA
tick. A persistent missing action becomes `AvTimeout`, never normal zero
control.

## Cleanup Appears Stuck

The wrapper switches CARLA to asynchronous mode and clears fixed delta time
before destroying actors. If an external process still blocks, confirm that it
is not independently forcing synchronous mode. Enable
`manage_traffic_manager_sync` only when this wrapper owns TrafficManager sync.
