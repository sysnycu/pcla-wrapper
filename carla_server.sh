#!/usr/bin/env bash
set -euo pipefail

CARLA_ROOT="${CARLA_ROOT:-/opt/carla}"
CARLA_EXECUTABLE="${CARLA_EXECUTABLE:-${CARLA_ROOT}/CarlaUE4.sh}"

if [[ ! -x "${CARLA_EXECUTABLE}" ]]; then
    echo "CARLA executable is not available: ${CARLA_EXECUTABLE}" >&2
    exit 127
fi

exec "${CARLA_EXECUTABLE}" \
    -RenderOffScreen \
    -nullrhi \
    -nosound \
    "-carla-port=${CARLA_PORT:-2000}"
