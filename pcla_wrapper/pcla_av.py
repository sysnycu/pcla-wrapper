from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from threading import RLock
from typing import Any

from pisa_api.av import (
    AvError,
    AvPreconditionFailed,
    AvTimeout,
    AvUnavailable,
    ControlCommand,
    ControlMode,
    InitRequest,
    InvalidAvRequest,
    ObjectStateData,
    ResetRequest,
    ResetResponse,
    RoadObjectType,
    ScenarioPackData,
    ShouldQuitResponse,
    StepRequest,
    StepResponse,
)

from .lifecycle import clear_dynamic_actors, destroy_actor, force_async_world_for_cleanup

logger = logging.getLogger(__name__)

OBJECT_IDENTITY_ATTRS = ("id", "object_id", "track_id", "external_id", "name")
OBJECT_IDENTITY_MODES = {"index", "provided", "stateless"}
BLUEPRINT_CANDIDATES = {
    RoadObjectType.PEDESTRIAN: ("walker.pedestrian.0001", "walker.pedestrian.*", "walker.*"),
    RoadObjectType.BUS: ("vehicle.mitsubishi.fusorosa", "vehicle.*bus*", "vehicle.*"),
    RoadObjectType.TRUCK: ("vehicle.carlamotors.carlacola", "vehicle.*truck*", "vehicle.*"),
    RoadObjectType.SEMITRAILER: ("vehicle.carlamotors.carlacola", "vehicle.*truck*", "vehicle.*"),
    RoadObjectType.TRAILER: ("vehicle.carlamotors.firetruck", "vehicle.*truck*", "vehicle.*"),
    RoadObjectType.VAN: ("vehicle.mercedes.sprinter", "vehicle.*van*", "vehicle.*"),
    RoadObjectType.MOTORCYCLE: ("vehicle.vespa.zx125", "vehicle.*motorcycle*", "vehicle.*"),
    RoadObjectType.BICYCLE: ("vehicle.bh.crossbike", "vehicle.*bike*", "vehicle.*"),
    RoadObjectType.TRAIN: ("vehicle.*",),
    RoadObjectType.TRAM: ("vehicle.*",),
    RoadObjectType.WHEEL_CHAIR: ("walker.pedestrian.*", "walker.*"),
    RoadObjectType.ANIMAL: ("walker.pedestrian.*", "walker.*"),
    RoadObjectType.CAR: ("vehicle.*",),
    RoadObjectType.UNKNOWN: ("vehicle.*",),
}


class PclaAV:
    """PISA lifecycle adapter for PCLA agents running in a shadow CARLA world."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._carla = None
        self._pcla_module = None
        self._data_provider = None
        self._client = None
        self._world = None
        self._map = None
        self._server_process = None
        self._server_version = None
        self._server_owned = False
        self._pcla = None
        self._vehicle = None
        self._other_actors_by_key: dict[Any, Any] = {}
        self._other_actor_types_by_key: dict[Any, RoadObjectType] = {}
        self._spawned_actor_ids: set[int] = set()
        self._loaded_map_name = None
        self._loaded_opendrive_path = None
        self._finalized = True
        self._initialized = False
        self._quit_flag = False
        self._quit_msg = ""
        self._last_error = ""
        self._last_timestamp_ns = 0
        self.config: dict[str, Any] = {}
        self._output_dir = Path()

    def init(self, request: InitRequest) -> None:
        with self._lock:
            if not self._finalized:
                self._finalize()
            self._output_dir = Path(request.output_dir)
            self.config = self._normalize_config(request.config or {})
            self._fixed_delta_seconds = self._positive_float("dt", request.dt)
            self._parse_config()
            self._validate_agent_name()
            if self._launch_carla_server and self._server_process is None:
                self._launch_server()
            if not self._ensure_connected():
                self._terminate_server_process()
                raise AvTimeout(
                    f"Timed out connecting to CARLA at {self._host}:{self._port} "
                    f"after {self._connect_timeout:.1f}s"
                )
            self._prepare_reused_server_state()
            self._quit_flag = False
            self._quit_msg = ""
            self._last_error = ""
            self._initialized = True

    def reset(self, request: ResetRequest) -> ResetResponse:
        with self._lock:
            if not self._initialized:
                raise AvPreconditionFailed("PCLA wrapper must be initialized before reset")
            if not self._finalized:
                self._finalize()
            self._finalized = False
            self._output_dir = Path(request.output_dir)
            scenario = request.scenario_pack
            observation = request.initial_observation
            self._quit_flag = False
            self._quit_msg = ""
            self._last_error = ""
            try:
                self._validate_reset_request(scenario, observation)
                self._ensure_world(scenario.map_name)
                self._cleanup_wrapper_actors()
                self._vehicle = self._spawn_ego(observation, scenario)
                self._apply_world_settings()
                self._set_data_provider()
                route_path = self._resolve_route_path(scenario, observation)
                self._pcla = self._build_pcla(route_path)
                return ResetResponse(
                    ctrl_cmd=self.step(
                        StepRequest(observation=observation, timestamp_ns=0)
                    ).ctrl_cmd
                )
            except Exception:
                logger.exception("PCLA reset failed; cleaning partial state")
                self._finalize()
                raise

    def step(self, request: StepRequest) -> StepResponse:
        with self._lock:
            if not request.observation:
                raise InvalidAvRequest("Step observation must include ego state")
            if self._pcla is None or self._vehicle is None:
                raise AvPreconditionFailed("PCLA scenario is not ready; call reset first")
            self._last_timestamp_ns = int(request.timestamp_ns)
            try:
                snapshot = self._update_and_tick(request.observation)
                if self._data_provider is not None:
                    self._data_provider.on_carla_tick()
                action = self._get_action(snapshot)
            except AvError:
                raise
            except Exception as exc:
                self._set_fatal_error(f"PCLA step failed: {exc}")
                logger.exception("PCLA step failed")
                raise AvUnavailable(str(exc)) from exc

            if action is None:
                message = "PCLA returned no action for the current CARLA frame"
                self._set_fatal_error(message)
                if self._action_none_timeout > 0:
                    raise AvTimeout(message)
                raise AvPreconditionFailed(message)

            if hasattr(self._pcla, "done") and self._pcla.done():
                self._quit_flag = True
                self._quit_msg = "PCLA agent reached the route endpoint."
            return StepResponse(
                ctrl_cmd=ControlCommand(
                    mode=ControlMode.THROTTLE_STEER_BREAK,
                    payload={
                        "throttle": float(action.throttle),
                        "brake": float(action.brake),
                        "steer": float(action.steer) / self._steer_sign,
                    },
                )
            )

    def stop(self) -> None:
        with self._lock:
            self._finalize()
            self._terminate_server_process()
            self._client = None
            self._server_version = None
            self._world = None
            self._map = None
            self._loaded_map_name = None
            self._loaded_opendrive_path = None
            self._pcla_module = None
            self._data_provider = None
            self._initialized = False
            self._quit_flag = True
            self._quit_msg = "PCLA service stopped."

    def should_quit(self) -> ShouldQuitResponse:
        process = self._server_process
        if self._server_owned and process is not None:
            return_code = process.poll()
            if return_code is not None:
                self._set_fatal_error(
                    f"Owned CARLA server exited unexpectedly with return code {return_code}."
                )
        return ShouldQuitResponse(should_quit=self._quit_flag, msg=self._quit_msg)

    def _normalize_config(self, raw: dict[str, Any]) -> dict[str, Any]:
        config = dict(raw)
        nested_pcla = config.pop("pcla", None)
        nested_carla = config.pop("carla", None)
        pcla_aliases = {
            "agent": "pcla_agent",
            "agent_name": "pcla_agent",
            "route_path": "route_xml_path",
        }
        carla_aliases = {
            "host": "carla_host",
            "port": "carla_port",
            "timeout": "carla_timeout",
        }
        for section_name, section, aliases in (
            ("pcla", nested_pcla, pcla_aliases),
            ("carla", nested_carla, carla_aliases),
        ):
            if section is None:
                continue
            if not isinstance(section, dict):
                raise InvalidAvRequest(f"{section_name} config must be a mapping")
            for old_key, value in section.items():
                key = aliases.get(old_key, old_key)
                if key in config and config[key] != value:
                    raise InvalidAvRequest(f"Conflicting flat and nested config values for {key!r}")
                config[key] = value
        return config

    def _parse_config(self) -> None:
        default_root = Path(__file__).resolve().parents[1] / "PCLA-wrapper" / "PCLA"
        self._pcla_root = Path(self.config.get("pcla_root", default_root)).resolve()
        self._agent_name = str(
            os.environ.get("PCLA_AGENT", self.config.get("pcla_agent", "carl_plant_3"))
        )
        route_override = os.environ.get("PCLA_ROUTE")
        self._route_path_cfg = route_override or self.config.get("route_xml_path")
        self._route_wp_distance = self._config_float("route_waypoint_distance", 2.0)
        self._route_draw = bool(self.config.get("route_draw", False))
        self._launch_carla_server = bool(self.config.get("launch_carla_server", True))
        self._connect_timeout = self._config_float(
            "carla_connect_timeout_seconds",
            self._config_float("max_retry_times", 15.0) * 2.0,
        )
        self._retry_interval = self._config_float("retry_interval_seconds", 2.0)
        if self._connect_timeout <= 0:
            raise InvalidAvRequest("carla_connect_timeout_seconds must be positive")
        if self._retry_interval <= 0:
            raise InvalidAvRequest("retry_interval_seconds must be positive")
        self._host = os.environ.get("CARLA_HOST", str(self.config.get("carla_host", "localhost")))
        try:
            self._port = int(os.environ.get("CARLA_PORT", self.config.get("carla_port", 2000)))
            self._traffic_manager_port = int(os.environ.get("CARLA_TM_PORT", 8000))
        except (TypeError, ValueError) as exc:
            raise InvalidAvRequest("CARLA_PORT and CARLA_TM_PORT must be integers") from exc
        self._carla_timeout = self._env_float(
            "CARLA_TIMEOUT", self._config_float("carla_timeout", 10.0)
        )
        self._sync = bool(self.config.get("sync", True))
        self._no_rendering = bool(self.config.get("no_rendering", True))
        self._xodr_root = Path(self.config.get("xodr_root", "/mnt/map/xodr"))
        self._reuse_generated_world = bool(self.config.get("reuse_generated_world", True))
        self._manage_traffic_manager_sync = bool(
            self.config.get("manage_traffic_manager_sync", False)
        )
        self._ego_role_name = str(self.config.get("ego_role_name", "hero"))
        self._ego_bp_id = str(self.config.get("ego_bp_id", "vehicle.tesla.model3"))
        self._spawn_z_offset = self._config_float("spawn_z_offset", 3.0)
        self._coordinate_y_sign = self._config_sign("coordinate_y_sign", -1.0)
        self._yaw_sign = self._config_sign("yaw_sign", -1.0)
        self._steer_sign = self._config_sign("steer_sign", -1.0)
        self._yaw_offset_deg = self._config_float("yaw_offset_deg", 0.0)
        self._object_identity_mode = str(
            self.config.get("object_identity_mode", "stateless")
        ).lower()
        if self._object_identity_mode not in OBJECT_IDENTITY_MODES:
            raise InvalidAvRequest(
                f"Unsupported object_identity_mode: {self._object_identity_mode!r}. "
                f"Expected one of: {', '.join(sorted(OBJECT_IDENTITY_MODES))}"
            )
        self._action_none_timeout = self._config_float("action_none_timeout_seconds", 0.0)
        if self._action_none_timeout < 0:
            raise InvalidAvRequest("action_none_timeout_seconds must be non-negative")

    def _config_float(self, name: str, default: float) -> float:
        raw = self.config.get(name, default)
        try:
            return float(raw)
        except (TypeError, ValueError) as exc:
            raise InvalidAvRequest(f"{name} must be a float, got {raw!r}") from exc

    @staticmethod
    def _positive_float(name: str, raw: Any) -> float:
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise InvalidAvRequest(f"{name} must be a float, got {raw!r}") from exc
        if value <= 0:
            raise InvalidAvRequest(f"{name} must be positive")
        return value

    def _config_sign(self, name: str, default: float) -> float:
        value = self._config_float(name, default)
        if abs(value) < 1e-6:
            raise InvalidAvRequest(f"{name} must be non-zero")
        return 1.0 if value > 0 else -1.0

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name, default))
        except (TypeError, ValueError) as exc:
            raise InvalidAvRequest(f"{name} must be a float") from exc

    def _validate_agent_name(self) -> None:
        agents_path = self._pcla_root / "agents.json"
        if not agents_path.is_file():
            raise InvalidAvRequest(f"PCLA agents registry not found: {agents_path}")
        try:
            agents = json.loads(agents_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidAvRequest(f"Failed to read PCLA agents registry: {agents_path}") from exc
        parts = self._agent_name.split("_")
        if len(parts) not in (2, 3) or not all(parts[:2]):
            raise InvalidAvRequest(
                "PCLA agent must use <family>_<variant>[_seed], for example carl_plant_3"
            )
        family, variant = parts[:2]
        if len(parts) == 3 and (not parts[2] or not parts[2].isdigit()):
            raise InvalidAvRequest("PCLA agent seed suffix must be an integer")
        if family not in agents or variant not in agents[family]:
            formats = [
                f"{family_name}_{variant_name}[_seed]"
                for family_name, variants in agents.items()
                for variant_name in variants
            ]
            raise InvalidAvRequest(
                f"Unknown PCLA agent {self._agent_name!r}. Accepted formats: "
                + ", ".join(sorted(formats))
            )

    def _ensure_carla_imports(self) -> None:
        if self._carla is not None:
            return
        carla_root = self.config.get("carla_root") or os.environ.get("CARLA_ROOT")
        carla_api = self.config.get("carla_egg")
        entries: list[Path] = []
        if carla_root:
            root = Path(carla_root)
            entries.extend((root / "PythonAPI", root / "PythonAPI" / "carla"))
            if not carla_api:
                dist = root / "PythonAPI" / "carla" / "dist"
                matches = sorted((*dist.glob("*.whl"), *dist.glob("*.egg")))
                carla_api = matches[0] if matches else None
        if carla_api:
            entries.append(Path(carla_api))
        for entry in entries:
            if str(entry) not in sys.path:
                sys.path.insert(0, str(entry))
        try:
            import carla
        except Exception as exc:
            raise AvUnavailable("CARLA Python API is not available") from exc
        self._carla = carla

    def _ensure_pcla_imports(self) -> None:
        if self._pcla_module is not None:
            return
        if not self._pcla_root.is_dir():
            raise AvUnavailable(f"PCLA root not found: {self._pcla_root}")
        if str(self._pcla_root) not in sys.path:
            sys.path.insert(0, str(self._pcla_root))
        try:
            import PCLA
            from leaderboard_codes.carla_data_provider import CarlaDataProvider
        except Exception as exc:
            raise AvUnavailable(f"Failed to import PCLA from {self._pcla_root}") from exc
        self._pcla_module = PCLA
        self._data_provider = CarlaDataProvider

    def _launch_server(self) -> None:
        log_dir = self._output_dir / "carla_server"
        log_dir.mkdir(parents=True, exist_ok=True)
        command = str(self.config.get("carla_server_script", "/app/carla_server.sh"))
        try:
            with contextlib.ExitStack() as stack:
                stdout = stack.enter_context((log_dir / "stdout.log").open("w", encoding="utf-8"))
                stderr = stack.enter_context((log_dir / "stderr.log").open("w", encoding="utf-8"))
                self._server_process = subprocess.Popen(
                    [command],
                    stdout=stdout,
                    stderr=stderr,
                    env=os.environ.copy(),
                )
        except OSError as exc:
            raise AvUnavailable(f"Failed to launch CARLA server with {command}") from exc
        self._server_owned = True
        logger.info("Launched owned CARLA server process %s", self._server_process.pid)

    def _connect_once(self) -> None:
        self._ensure_carla_imports()
        client = self._carla.Client(self._host, self._port)
        try:
            client.set_timeout(min(2.0, self._carla_timeout))
            version = client.get_server_version()
            world = client.get_world()
            if world is None:
                raise RuntimeError("CARLA returned no world")
        finally:
            client.set_timeout(self._carla_timeout)
        self._client = client
        self._server_version = version

    def _ensure_connected(self) -> bool:
        if self._server_version is not None and self._client is not None:
            return True
        deadline = time.monotonic() + self._connect_timeout
        while True:
            try:
                self._connect_once()
                return True
            except Exception:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logger.exception("Timed out connecting to CARLA")
                    return False
                logger.warning("CARLA connection failed; retrying", exc_info=True)
                time.sleep(min(self._retry_interval, remaining))

    def _prepare_reused_server_state(self) -> None:
        if self._client is None:
            return
        previous_world = self._world
        try:
            self._world = self._client.get_world()
            self._map = self._world.get_map()
        except Exception as exc:
            raise AvUnavailable("Failed to inspect existing CARLA world") from exc
        if self._world is not previous_world:
            self._loaded_map_name = None
            self._loaded_opendrive_path = None
        clear_dynamic_actors(
            self._world,
            client=self._client,
            traffic_manager_port=self._traffic_manager_port,
            manage_traffic_manager=self._manage_traffic_manager_sync,
            log=logger,
        )

    def _validate_reset_request(
        self,
        scenario: ScenarioPackData | None,
        observation: list[ObjectStateData],
    ) -> None:
        if scenario is None:
            raise InvalidAvRequest("ScenarioPack is required")
        if not getattr(scenario, "map_name", ""):
            raise InvalidAvRequest("ScenarioPack map_name is required")
        if not observation:
            raise InvalidAvRequest("Initial observation must include ego state")
        self._extract_xyz(observation[0].kinematic)
        if self._get_goal_position(scenario) is None:
            raise InvalidAvRequest("ScenarioPack ego goal position is required")

    def _ensure_world(self, map_name: str) -> None:
        if self._client is None:
            raise AvUnavailable("CARLA client is not available")
        path = (self._xodr_root / f"{map_name}.xodr").resolve()
        if (
            self._reuse_generated_world
            and self._world is not None
            and self._loaded_map_name == map_name
            and self._loaded_opendrive_path == path
        ):
            self._map = self._world.get_map()
            return
        if not path.is_file():
            raise InvalidAvRequest(f"OpenDRIVE map not found: {path}")
        try:
            opendrive = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise InvalidAvRequest(f"Failed to read OpenDRIVE map: {path}") from exc
        self._client.set_timeout(300.0)
        try:
            try:
                world = self._client.generate_opendrive_world(
                    opendrive,
                    self._carla.OpendriveGenerationParameters(
                        vertex_distance=2.0,
                        max_road_length=3000.0,
                        wall_height=0.0,
                        additional_width=0.6,
                        smooth_junctions=True,
                        enable_mesh_visibility=True,
                    ),
                )
            except Exception as exc:
                raise AvPreconditionFailed(
                    f"Failed to generate CARLA world from OpenDRIVE map: {path}"
                ) from exc
        finally:
            self._client.set_timeout(self._carla_timeout)
        if world is None:
            raise AvUnavailable("CARLA returned no generated world")
        self._world = world
        try:
            self._map = world.get_map()
        except Exception as exc:
            raise AvPreconditionFailed("Generated CARLA world has no readable map") from exc
        self._loaded_map_name = map_name
        self._loaded_opendrive_path = path

    def _apply_world_settings(self) -> None:
        settings = self._world.get_settings()
        settings.synchronous_mode = self._sync
        settings.no_rendering_mode = self._no_rendering
        settings.fixed_delta_seconds = self._fixed_delta_seconds
        self._world.apply_settings(settings)

    def _set_data_provider(self) -> None:
        self._ensure_pcla_imports()
        self._data_provider.set_client(self._client)
        self._data_provider.set_world(self._world)

    def _extract_xyz(self, pos: Any) -> tuple[float, float, float]:
        if pos is None:
            raise InvalidAvRequest("Position is required")
        world = getattr(pos, "world", None)
        source = world if world is not None else pos
        missing = [name for name in ("x", "y", "z") if not hasattr(source, name)]
        if missing:
            raise InvalidAvRequest(f"Position is missing coordinate field(s): {', '.join(missing)}")
        try:
            return float(source.x), float(source.y), float(source.z)
        except (TypeError, ValueError) as exc:
            raise InvalidAvRequest("Position coordinates must be numeric") from exc

    def _extract_yaw(self, pos: Any) -> float:
        source = getattr(pos, "world", None) or pos
        raw = getattr(source, "h", getattr(pos, "yaw", getattr(pos, "h", 0.0)))
        try:
            return float(raw)
        except (TypeError, ValueError) as exc:
            raise InvalidAvRequest("Position yaw must be numeric radians") from exc

    def _to_carla_location(self, pos: Any):
        x, y, z = self._extract_xyz(pos)
        return self._carla.Location(x=x, y=y * self._coordinate_y_sign, z=z)

    def _to_carla_yaw(self, yaw_rad: float) -> float:
        return self._yaw_sign * math.degrees(float(yaw_rad)) + self._yaw_offset_deg

    def _find_blueprint(self, library: Any, candidates: tuple[str, ...]):
        for pattern in candidates:
            try:
                if "*" not in pattern:
                    return library.find(pattern)
                matches = library.filter(pattern)
            except Exception:
                continue
            if matches:
                return matches[0]
        return None

    def _spawn_ego(
        self,
        observation: list[ObjectStateData],
        scenario: ScenarioPackData,
    ):
        blueprint = self._find_blueprint(
            self._world.get_blueprint_library(), (self._ego_bp_id, "vehicle.*")
        )
        if blueprint is None:
            raise AvPreconditionFailed("No CARLA vehicle blueprint is available for ego")
        if blueprint.has_attribute("role_name"):
            blueprint.set_attribute("role_name", self._ego_role_name)
        pos = self._get_spawn_position(observation, scenario)
        location = self._to_carla_location(pos)
        location.z += self._spawn_z_offset
        transform = self._carla.Transform(
            location,
            self._carla.Rotation(
                pitch=0.0, yaw=self._to_carla_yaw(self._extract_yaw(pos)), roll=0.0
            ),
        )
        ego = self._spawn_actor_allowing_observation_overlap(blueprint, transform)
        if ego is None:
            raise AvPreconditionFailed("Failed to spawn ego vehicle")
        self._spawned_actor_ids.add(ego.id)
        return ego

    def _get_spawn_position(
        self,
        observation: list[ObjectStateData],
        scenario: ScenarioPackData,
    ):
        if observation:
            return observation[0].kinematic
        ego = getattr(scenario, "ego", None)
        spawn = getattr(ego, "spawn_config", None)
        return getattr(spawn, "position", None)

    @staticmethod
    def _get_goal_position(scenario: ScenarioPackData):
        ego = getattr(scenario, "ego", None)
        goal = getattr(ego, "goal_config", None)
        return getattr(goal, "position", None)

    def _resolve_route_path(
        self,
        scenario: ScenarioPackData,
        observation: list[ObjectStateData],
    ) -> Path:
        if self._route_path_cfg:
            path = Path(self._route_path_cfg)
            if not path.is_absolute():
                path = (self._pcla_root / path).resolve()
            if not path.is_file() or not os.access(path, os.R_OK):
                raise InvalidAvRequest(f"Configured route XML is not readable: {path}")
            return path

        self._ensure_pcla_imports()
        route_dir = self._output_dir / "pcla_routes"
        route_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", scenario.name or "scenario")
        safe_name = safe_name.strip("._") or "scenario"
        route_path = route_dir / f"{safe_name}.route.xml"

        start = self._to_carla_location(self._get_spawn_position(observation, scenario))
        goal = self._to_carla_location(self._get_goal_position(scenario))
        start_wp = self._map.get_waypoint(start, project_to_road=True)
        goal_wp = self._map.get_waypoint(goal, project_to_road=True)
        if start_wp is None or goal_wp is None:
            raise AvPreconditionFailed("Failed to project route endpoints onto the CARLA map")
        try:
            waypoints = self._pcla_module.location_to_waypoint(
                self._client,
                start_wp.transform.location,
                goal_wp.transform.location,
                distance=self._route_wp_distance,
                draw=self._route_draw,
            )
        except Exception as exc:
            raise AvPreconditionFailed("PCLA route planner failed") from exc
        if len(waypoints) < 2:
            raise AvPreconditionFailed("PCLA route planner returned fewer than two waypoints")
        endpoints = [waypoints[0], waypoints[-1]]
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=route_dir,
                prefix=f".{safe_name}.",
                suffix=".xml",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
            self._pcla_module.route_maker(endpoints, savePath=str(temp_path))
            if not temp_path.is_file() or temp_path.stat().st_size == 0:
                raise AvPreconditionFailed("PCLA route writer produced an empty route")
            os.replace(temp_path, route_path)
        except AvError:
            raise
        except Exception as exc:
            raise AvPreconditionFailed("Failed to write PCLA route XML") from exc
        finally:
            if temp_path is not None:
                with contextlib.suppress(FileNotFoundError):
                    temp_path.unlink()
        return route_path

    def _build_pcla(self, route_path: Path):
        self._ensure_pcla_imports()
        try:
            return self._pcla_module.PCLA(
                self._agent_name,
                self._vehicle,
                str(route_path),
                self._client,
                destroy_vehicle=False,
            )
        except TimeoutError as exc:
            raise AvTimeout(f"Timed out loading PCLA agent {self._agent_name!r}") from exc
        except (FileNotFoundError, ImportError, ModuleNotFoundError) as exc:
            raise AvUnavailable(
                f"PCLA agent {self._agent_name!r} dependencies or weights are unavailable: {exc}"
            ) from exc

    def _get_action(self, snapshot: Any):
        deadline = time.monotonic() + self._action_none_timeout
        while True:
            try:
                action = self._pcla.get_action(snapshot=snapshot)
            except TypeError as exc:
                if "snapshot" not in str(exc):
                    raise
                action = self._pcla.get_action()
            if action is not None or self._action_none_timeout <= 0:
                return action
            if time.monotonic() >= deadline:
                return None
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))

    def _provided_object_identity(self, obj: ObjectStateData):
        for attr in OBJECT_IDENTITY_ATTRS:
            value = getattr(obj, attr, None)
            if value not in (None, ""):
                return attr, value
        return None

    def _object_identity(self, obj: ObjectStateData, index: int):
        if self._object_identity_mode == "index":
            return "index", index
        if self._object_identity_mode == "stateless":
            return "frame", index
        identity = self._provided_object_identity(obj)
        if identity is None:
            raise InvalidAvRequest(
                "object_identity_mode='provided' requires one of: "
                + ", ".join(OBJECT_IDENTITY_ATTRS)
            )
        return identity

    @staticmethod
    def _role_name_for_object_key(key: Any) -> str:
        raw = "_".join(str(part) for part in key)
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", raw)
        return f"agent_{safe}"[:255]

    def _spawn_actor_allowing_observation_overlap(self, blueprint: Any, transform: Any):
        actor = self._world.try_spawn_actor(blueprint, transform)
        if actor is not None:
            return actor
        base = transform.location
        for offset in (max(self._spawn_z_offset, 5.0), 10.0, 20.0, 50.0):
            elevated = self._carla.Transform(
                self._carla.Location(base.x, base.y, base.z + offset),
                transform.rotation,
            )
            actor = self._world.try_spawn_actor(blueprint, elevated)
            if actor is not None:
                return actor
        return None

    def _make_observation_actor_kinematic(self, actor: Any) -> None:
        with contextlib.suppress(Exception):
            actor.set_simulate_physics(False)
        with contextlib.suppress(Exception):
            actor.set_enable_gravity(False)

    def _apply_kinematic(self, actor: Any, kin: Any, *, kinematic: bool = False) -> None:
        if kinematic:
            self._make_observation_actor_kinematic(actor)
        location = self._to_carla_location(kin)
        yaw = self._to_carla_yaw(float(kin.yaw))
        actor.set_transform(
            self._carla.Transform(location, self._carla.Rotation(pitch=0.0, yaw=yaw, roll=0.0))
        )
        yaw_rad = math.radians(yaw)
        velocity = self._carla.Vector3D(
            float(kin.speed) * math.cos(yaw_rad),
            float(kin.speed) * math.sin(yaw_rad),
            0.0,
        )
        try:
            actor.set_target_velocity(velocity)
        except Exception:
            with contextlib.suppress(Exception):
                actor.set_velocity(velocity)
        angular = self._carla.Vector3D(0.0, 0.0, math.degrees(float(kin.yaw_rate)) * self._yaw_sign)
        try:
            actor.set_target_angular_velocity(angular)
        except Exception:
            with contextlib.suppress(Exception):
                actor.set_angular_velocity(angular)

    def _update_and_tick(self, observation: list[ObjectStateData]):
        self._apply_kinematic(self._vehicle, observation[0].kinematic)
        if self._object_identity_mode == "stateless":
            self._destroy_other_actors()

        observed_keys = set()
        for index, obj in enumerate(observation[1:]):
            key = self._object_identity(obj, index)
            observed_keys.add(key)
            actor = self._other_actors_by_key.get(key)
            if (
                actor is None
                or not getattr(actor, "is_alive", True)
                or self._other_actor_types_by_key.get(key) != obj.type
            ):
                if actor is not None:
                    actor_id = getattr(actor, "id", None)
                    if destroy_actor(actor, log=logger):
                        self._spawned_actor_ids.discard(actor_id)
                candidates = BLUEPRINT_CANDIDATES.get(
                    obj.type, BLUEPRINT_CANDIDATES[RoadObjectType.UNKNOWN]
                )
                blueprint = self._find_blueprint(self._world.get_blueprint_library(), candidates)
                if blueprint is None:
                    raise AvPreconditionFailed(f"No CARLA blueprint for object type {obj.type}")
                if blueprint.has_attribute("role_name"):
                    blueprint.set_attribute("role_name", self._role_name_for_object_key(key))
                location = self._to_carla_location(obj.kinematic)
                transform = self._carla.Transform(
                    location,
                    self._carla.Rotation(
                        pitch=0.0,
                        yaw=self._to_carla_yaw(float(obj.kinematic.yaw)),
                        roll=0.0,
                    ),
                )
                actor = self._spawn_actor_allowing_observation_overlap(blueprint, transform)
                if actor is None:
                    raise AvPreconditionFailed(f"Failed to spawn actor for object {key}")
                self._spawned_actor_ids.add(actor.id)
                self._other_actors_by_key[key] = actor
                self._other_actor_types_by_key[key] = obj.type
            self._apply_kinematic(actor, obj.kinematic, kinematic=True)

        for key in set(self._other_actors_by_key) - observed_keys:
            actor = self._other_actors_by_key.pop(key)
            self._other_actor_types_by_key.pop(key, None)
            actor_id = getattr(actor, "id", None)
            if destroy_actor(actor, log=logger, label="stale actor"):
                self._spawned_actor_ids.discard(actor_id)

        if self._sync:
            self._world.tick()
        else:
            self._world.wait_for_tick()
        return self._world.get_snapshot()

    def _destroy_other_actors(self) -> None:
        for actor in list(self._other_actors_by_key.values()):
            actor_id = getattr(actor, "id", None)
            if destroy_actor(actor, log=logger):
                self._spawned_actor_ids.discard(actor_id)
        self._other_actors_by_key.clear()
        self._other_actor_types_by_key.clear()

    def _cleanup_wrapper_actors(self) -> None:
        if self._world is None:
            self._vehicle = None
            self._other_actors_by_key.clear()
            self._other_actor_types_by_key.clear()
            self._spawned_actor_ids.clear()
            return
        force_async_world_for_cleanup(
            self._world,
            client=self._client,
            traffic_manager_port=self._traffic_manager_port,
            manage_traffic_manager=self._manage_traffic_manager_sync,
            log=logger,
        )
        actors = [self._vehicle, *self._other_actors_by_key.values()]
        destroyed = set()
        for actor in actors:
            actor_id = getattr(actor, "id", None)
            if actor_id in destroyed:
                continue
            if destroy_actor(actor, log=logger):
                destroyed.add(actor_id)
        self._vehicle = None
        self._other_actors_by_key.clear()
        self._other_actor_types_by_key.clear()
        self._spawned_actor_ids.clear()

    def _finalize(self) -> None:
        if self._pcla is not None:
            try:
                self._pcla.cleanup()
            except Exception:
                logger.exception("Failed to cleanup PCLA")
            self._pcla = None
        self._cleanup_wrapper_actors()
        self._finalized = True
        self._quit_flag = True
        if not self._quit_msg:
            self._quit_msg = "PCLA scenario finalized."

    def _terminate_server_process(self) -> None:
        process = self._server_process
        if process is None:
            self._server_owned = False
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        except Exception:
            logger.exception("Failed to terminate owned CARLA server")
        finally:
            self._server_process = None
            self._server_owned = False

    def _set_fatal_error(self, message: str) -> None:
        self._last_error = message
        self._quit_flag = True
        self._quit_msg = message
