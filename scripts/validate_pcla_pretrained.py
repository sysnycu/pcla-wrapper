#!/usr/bin/env python3
"""Validate the PCLA registry and the official pretrained archive layout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_WEIGHT_PATHS = (
    "pcla_agents/carl_pretrained/CaRL_PY_0_0/config.json",
    "pcla_agents/interfuser_pretrained/interfuser.pth.tar",
    "pcla_agents/lav_pretrained/lidar_15.th",
    "pcla_agents/lav_pretrained/lidar_v2_7.th",
    "pcla_agents/lmdrive_pretrained/llama-7b-checkpoint.pth",
    "pcla_agents/lmdrive_pretrained/llava-v1.5-checkpoint.pth",
    "pcla_agents/lmdrive_pretrained/vicuna-v1.5-checkpoint.pth",
    "pcla_agents/lmdrive_pretrained/vision-encoder-r50.pth.tar",
    "pcla_agents/neat_pretrained/neat",
    "pcla_agents/plant2_pretrained/epoch=029_final_0.ckpt",
    "pcla_agents/plant2_pretrained/epoch=029_final_1.ckpt",
    "pcla_agents/plant2_pretrained/epoch=029_final_2.ckpt",
    "pcla_agents/plant_pretrained/last-v3.ckpt",
    "pcla_agents/simlingo_pretrained/checkpoints/epoch=013.ckpt/pytorch_model.pt",
    "pcla_agents/transfuserv3_pretrained/transfuser",
    "pcla_agents/transfuserv4_pretrained",
    "pcla_agents/transfuserv5_pretrained/all_towns",
    "pcla_agents/transfuserv6_pretrained/tfv6_regnety032",
    "pcla_agents/wor_pretrained/leaderboard_weights/main_model_10.th",
)


def registry_path_exists(path: Path) -> bool:
    if path.exists():
        return True
    if path.suffix:
        return any(path.parent.glob(f"{path.stem}*{path.suffix}"))
    return any(path.parent.glob(f"{path.name}*"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pcla-root",
        type=Path,
        default=Path("PCLA"),
        help="directory containing agents.json and pcla_agents",
    )
    args = parser.parse_args()
    pcla_root = args.pcla_root.resolve()

    registry_path = pcla_root / "agents.json"
    with registry_path.open(encoding="utf-8") as registry_file:
        registry = json.load(registry_file)

    missing: list[Path] = []
    for family in registry.values():
        for variant in family.values():
            for key in ("agent", "config"):
                path = pcla_root / variant[key]
                if not registry_path_exists(path):
                    missing.append(path)

    for relative_path in REQUIRED_WEIGHT_PATHS:
        path = pcla_root / relative_path
        if not path.exists():
            missing.append(path)

    if missing:
        print("Missing PCLA files:")
        for path in sorted(set(missing)):
            print(f"  {path}")
        return 1

    print(f"PCLA registry and pretrained weights are valid under {pcla_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
