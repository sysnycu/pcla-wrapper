#!/usr/bin/env bash
set -euo pipefail

exec /opt/conda/envs/PCLA/bin/python -m pcla_wrapper.server
