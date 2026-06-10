# Configuration

The wrapper receives configuration through `pisa_api.av.InitRequest.config`.
Use a flat mapping as shown in [`config_example.yaml`](../config_example.yaml).
The simulation time step is supplied separately as `InitRequest.dt`.

## Precedence

Values are resolved in this order:

1. Environment overrides: `PCLA_AGENT`, `PCLA_ROUTE`, `CARLA_HOST`,
   `CARLA_PORT`, and `CARLA_TIMEOUT`.
2. Flat `InitRequest.config` keys.
3. Legacy nested `pcla:` and `carla:` keys.
4. Wrapper defaults.

If a flat key and its legacy nested equivalent are both present with different
values, Init fails with `InvalidAvRequest`.

## PCLA

| Key | Default | Description |
| --- | --- | --- |
| `pcla_agent` | `carl_plant_3` | Registry name `<family>_<variant>[_seed]`. |
| `pcla_root` | Repository PCLA submodule | Directory containing `PCLA.py` and `agents.json`. |
| `route_xml_path` | `null` | Existing route XML, or generate one from scenario start/goal. |
| `route_waypoint_distance` | `2.0` | Route planner sampling distance in meters. |
| `route_draw` | `false` | Draw route debug markers in CARLA. |
| `action_none_timeout_seconds` | `0.0` | Retry window when PCLA returns no action. |

`route_xml_path` is resolved relative to `pcla_root` unless it is absolute.
Generated routes are written below
`<ResetRequest.output_dir>/pcla_routes/`.

## CARLA Connection And Process

| Key | Default | Description |
| --- | --- | --- |
| `launch_carla_server` | `true` | Launch a wrapper-owned CARLA process. |
| `carla_server_script` | `/app/carla_server.sh` | Server launcher executable. |
| `carla_host` | `localhost` | CARLA RPC host when `CARLA_HOST` is absent. |
| `carla_port` | `2000` | CARLA RPC port when `CARLA_PORT` is absent. |
| `carla_connect_timeout_seconds` | `30.0` | Total connection retry window. |
| `retry_interval_seconds` | `2.0` | Delay between connection attempts. |
| `max_retry_times` | `15` | Legacy fallback used only when total timeout is omitted. |
| `carla_timeout` | `10.0` | Normal CARLA RPC timeout. |
| `carla_root` | unset | Optional local CARLA Python API root. |
| `carla_egg` | unset | Optional CARLA wheel/egg path. |

The wrapper terminates CARLA only when it launched that process. For an
external server, set `launch_carla_server: false`.

## World And Actors

| Key | Default | Description |
| --- | --- | --- |
| `sync` | `true` | Use CARLA synchronous mode. |
| `no_rendering` | `true` | Disable rendering. Camera agents may require `false`. |
| `xodr_root` | `/mnt/map/xodr` | OpenDRIVE map directory. |
| `reuse_generated_world` | `true` | Reuse an unchanged generated map between resets. |
| `manage_traffic_manager_sync` | `false` | Set TrafficManager async during cleanup. |
| `ego_role_name` | `hero` | Ego blueprint role name. |
| `ego_bp_id` | `vehicle.tesla.model3` | Preferred ego blueprint. |
| `spawn_z_offset` | `3.0` | Ego spawn height offset in meters. |
| `object_identity_mode` | `stateless` | Non-ego identity strategy. |

Identity modes:

- `stateless`: rebuild non-ego actors every frame.
- `index`: preserve actors by observation order.
- `provided`: use `id`, `object_id`, `track_id`, `external_id`, or `name`.

Observation-controlled non-ego actors have physics and gravity disabled. Ego
physics remains enabled.

## Coordinates

| Key | Default | Formula |
| --- | --- | --- |
| `coordinate_y_sign` | `-1.0` | `carla_y = pisa_y * sign` |
| `yaw_sign` | `-1.0` | `carla_yaw_deg = sign * degrees(pisa_yaw) + offset` |
| `steer_sign` | `-1.0` | `pisa_steer = pcla_steer / sign` |
| `yaw_offset_deg` | `0.0` | Constant heading offset in degrees. |

All sign values must be non-zero and are normalized to `+1` or `-1`. PISA yaw
and yaw rate are always interpreted as radians.

## Legacy Nested Form

This compatibility form remains accepted:

```yaml
pcla:
  agent: carl_plant_3
  pcla_root: /app/PCLA-wrapper/PCLA
  route_path: null

carla:
  host: localhost
  port: 2000
  timeout: 10.0
  sync: true
```

New deployments should use flat keys because the nested form is temporary.
