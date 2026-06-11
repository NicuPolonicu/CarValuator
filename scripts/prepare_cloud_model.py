from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import joblib


DEFAULT_MODELS = [
    "svr_rbf",
    "ridge",
    "knn_distance",
    "gradient_boosting",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a smaller CarValuator model bundle for cloud demos.")
    parser.add_argument("source", type=Path, help="Full best_model.joblib produced by training")
    parser.add_argument("output", type=Path, help="Destination cloud model bundle")
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS, help="Pipeline names to keep")
    parser.add_argument("--compress", type=int, default=3, choices=range(0, 10), help="joblib compression level")
    return parser.parse_args()


def build_cloud_bundle(bundle: dict[str, Any], model_names: list[str]) -> dict[str, Any]:
    available_pipelines = bundle.get("all_pipelines") or {}
    missing = [name for name in model_names if name not in available_pipelines]
    if missing:
        raise ValueError(f"Unknown model names: {', '.join(missing)}")

    selected_pipelines = {name: available_pipelines[name] for name in model_names}
    primary_name = model_names[0]
    return {
        **bundle,
        "pipeline": selected_pipelines[primary_name],
        "model_name": primary_name,
        "all_pipelines": selected_pipelines,
        "metrics": [
            metric
            for metric in bundle.get("metrics", [])
            if metric.get("model") in selected_pipelines
        ],
        "cloud_bundle": True,
        "cloud_models": model_names,
    }


def main() -> None:
    args = parse_args()
    bundle = joblib.load(args.source)
    cloud_bundle = build_cloud_bundle(bundle, args.models)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(cloud_bundle, args.output, compress=args.compress)
    print(f"Created {args.output} ({args.output.stat().st_size / 1024 / 1024:.2f} MB)")
    print(f"Models: {', '.join(args.models)}")


if __name__ == "__main__":
    main()
