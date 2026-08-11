from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.config import get_settings
from app.data.pipeline.features import build_sliding_windows
from app.ml.spatial_diagnostics import (
    add_default_context_buckets,
    blend_alpha_sweep,
    calibration_bins,
    fallback_audit,
    group_brier_diagnostics,
    local_route_diagnostics,
    markdown_table,
    slice_brier_diagnostics,
)
from app.ml.training import (
    _eligible_holdout_groups,
    _inject_agent_features,
    _load_curated_training_frame,
    _metadata_with_groups,
    _spatial_holdout_fold_result,
)
from app.ml.weather_delta import fit_smoothed_rate_prior
from app.ml.stale_evaluation import (
    build_stale_censoring_variants,
    filter_stale_rows,
    stale_row_label,
)


DEFAULT_CONTEXT_COLUMNS = [
    "precip_24h_bucket",
    "rain_72h_bucket",
    "wave_height_bucket",
    "wave_recency_bucket",
    "sample_recency_bucket",
    "rain_72h_general_advisory_flag",
    "rain_72h_monitoring_pause_flag",
]

FEATURE_CONTEXT_COLUMNS = [
    "precip_mm_24h",
    "precip_mm_72h",
    "precip_mm_7d",
    "precip_awi",
    "rain_72h_inches",
    "rain_72h_general_advisory_flag",
    "rain_72h_monitoring_pause_flag",
    "wave_height_m_last_obs",
    "days_since_wave_height_m_obs",
    "dominant_period_s_last_obs",
    "days_since_dominant_period_s_obs",
    "enterococcus_action_ratio_last_obs",
    "days_since_enterococcus_value_obs",
    "streamflow_cfs_mean_24h",
    "streamflow_rising_flag",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parse_alphas(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def _parse_ints(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _prepare_inputs(
    curated_dir: Path,
    *,
    training_window_days: int,
) -> tuple[pd.DataFrame, np.ndarray, pd.DataFrame]:
    full_frame = _load_curated_training_frame(curated_dir)
    full_frame["sample_date"] = pd.to_datetime(full_frame["sample_date"])
    max_date = full_frame["sample_date"].max()
    frame = full_frame.loc[
        full_frame["sample_date"] > (max_date - pd.Timedelta(days=training_window_days))
    ].copy()
    stations = pd.read_parquet(curated_dir / "beaches.parquet")
    advisories_path = curated_dir / "advisories.parquet"
    advisories = pd.read_parquet(advisories_path) if advisories_path.exists() else pd.DataFrame()
    dataset = build_sliding_windows(frame)
    features = dataset.feature_frame.select_dtypes(include=["number"]).fillna(0.0)
    features = _inject_agent_features(features, dataset.metadata, full_frame, advisories, stations)
    labels = dataset.targets_exceed
    metadata = _metadata_with_groups(dataset.metadata, frame, stations=stations)
    return features, labels, metadata


def _collect_holdout_predictions(
    features: pd.DataFrame,
    labels: np.ndarray,
    metadata: pd.DataFrame,
    *,
    group_column: str,
    model_name: str,
    stv_threshold: float,
    min_rows: int,
    max_groups: int | None,
) -> pd.DataFrame:
    eligible = _eligible_holdout_groups(
        metadata,
        group_column=group_column,
        min_rows=min_rows,
        max_groups=max_groups,
    )
    rows: list[pd.DataFrame] = []
    for group_value in eligible.index.tolist():
        model_result = _spatial_holdout_fold_result(
            features,
            labels,
            metadata,
            model_name=model_name,
            group_column=group_column,
            group_value=group_value,
            stv_threshold=stv_threshold,
            min_rows=min_rows,
        )
        persistence_result = _spatial_holdout_fold_result(
            features,
            labels,
            metadata,
            model_name="persistence",
            group_column=group_column,
            group_value=group_value,
            stv_threshold=stv_threshold,
            min_rows=min_rows,
        )
        if model_result is None or persistence_result is None:
            continue

        fold_labels, model_probabilities = model_result
        persistence_labels, persistence_probabilities = persistence_result
        if not np.array_equal(fold_labels, persistence_labels):
            raise ValueError(f"Label mismatch while diagnosing {group_column}={group_value!r}")

        test_rows = np.flatnonzero(metadata[group_column].eq(group_value).to_numpy())
        if len(test_rows) != len(fold_labels):
            raise ValueError(f"Row mismatch while diagnosing {group_column}={group_value!r}")
        train_rows = np.flatnonzero(~metadata[group_column].eq(group_value).to_numpy())
        prior = fit_smoothed_rate_prior(labels, metadata, train_rows)

        fold_metadata = metadata.iloc[test_rows].reset_index(drop=True).copy()
        feature_context = features.iloc[test_rows].reset_index(drop=True)
        for column in FEATURE_CONTEXT_COLUMNS:
            if column in feature_context.columns:
                fold_metadata[column] = feature_context[column].to_numpy()
        fold_metadata["holdout_group_column"] = group_column
        fold_metadata["holdout_group"] = str(group_value)
        fold_metadata["label"] = fold_labels.astype(float)
        fold_metadata["model_probability"] = model_probabilities.astype(float)
        fold_metadata["persistence_probability"] = persistence_probabilities.astype(float)
        fold_metadata["prior_probability"] = prior.predict(fold_metadata)
        rows.append(fold_metadata)

    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def _write_markdown_summary(
    path: Path,
    *,
    group_column: str,
    model_name: str,
    predictions: pd.DataFrame,
    group_table: pd.DataFrame,
    blend_table: pd.DataFrame,
) -> None:
    best_blend = blend_table.sort_values("brier").iloc[0] if not blend_table.empty else None
    model_brier = float(((predictions["model_probability"] - predictions["label"]) ** 2).mean())
    persistence_brier = float(
        ((predictions["persistence_probability"] - predictions["label"]) ** 2).mean()
    )
    lines = [
        f"# Spatial Brier Diagnostics: {group_column}",
        "",
        f"- Generated at: {datetime.now(UTC).isoformat()}",
        f"- Model: `{model_name}`",
        f"- Rows: {len(predictions)}",
        f"- Groups: {predictions['holdout_group'].nunique()}",
        f"- Model Brier: {model_brier:.6f}",
        f"- Persistence Brier: {persistence_brier:.6f}",
        f"- Delta: {model_brier - persistence_brier:.6f}",
    ]
    if best_blend is not None:
        lines.extend(
            [
                f"- Best blend alpha: {float(best_blend['alpha']):.2f}",
                f"- Best blend Brier: {float(best_blend['brier']):.6f}",
                f"- Best blend delta vs persistence: {float(best_blend['brier_delta_vs_persistence']):.6f}",
            ]
        )
    lines.extend(["", "## Worst Groups", ""])
    if group_table.empty:
        lines.append("No group diagnostics were produced.")
    else:
        preview = group_table.head(10).copy()
        lines.append(markdown_table(preview, floatfmt=".4f"))
    path.write_text("\n".join(lines) + "\n")


def _write_outputs(
    output_dir: Path,
    *,
    group_column: str,
    model_name: str,
    predictions: pd.DataFrame,
    bins: int,
    alphas: list[float],
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    enriched = add_default_context_buckets(predictions)
    group_table = group_brier_diagnostics(enriched, group_column=group_column)
    local_router_table = local_route_diagnostics(enriched, group_column=group_column)
    model_bins = calibration_bins(enriched, probability_column="model_probability", bins=bins)
    persistence_bins = calibration_bins(enriched, probability_column="persistence_probability", bins=bins)
    blend_table = blend_alpha_sweep(enriched, alphas=alphas)
    prior_group_table = (
        group_brier_diagnostics(
            enriched,
            group_column=group_column,
            persistence_probability_column="prior_probability",
        )
        if "prior_probability" in enriched.columns
        else pd.DataFrame()
    )
    prior_local_router_table = (
        local_route_diagnostics(
            enriched,
            group_column=group_column,
            baseline_probability_column="prior_probability",
        )
        if "prior_probability" in enriched.columns
        else pd.DataFrame()
    )
    prior_audit = (
        fallback_audit(enriched, baseline_probability_column="prior_probability")
        if "prior_probability" in enriched.columns
        else {}
    )

    enriched.to_csv(output_dir / f"{group_column}_holdout_predictions.csv", index=False)
    group_table.to_csv(output_dir / f"{group_column}_brier_deltas.csv", index=False)
    local_router_table.to_csv(output_dir / f"{group_column}_local_router.csv", index=False)
    if not prior_group_table.empty:
        prior_group_table.to_csv(output_dir / f"{group_column}_prior_brier_deltas.csv", index=False)
        prior_local_router_table.to_csv(output_dir / f"{group_column}_prior_local_router.csv", index=False)
        (output_dir / f"{group_column}_prior_fallback_audit.json").write_text(
            json.dumps(prior_audit, indent=2) + "\n"
        )
    model_bins.to_csv(output_dir / f"{group_column}_model_calibration_bins.csv", index=False)
    persistence_bins.to_csv(
        output_dir / f"{group_column}_persistence_calibration_bins.csv",
        index=False,
    )
    blend_table.to_csv(output_dir / f"{group_column}_blend_alpha_sweep.csv", index=False)

    slice_paths: dict[str, str] = {}
    for column in DEFAULT_CONTEXT_COLUMNS:
        if column not in enriched.columns:
            continue
        table = slice_brier_diagnostics(enriched, slice_column=column)
        if table.empty:
            continue
        path = output_dir / f"{group_column}_slice_{column}.csv"
        table.to_csv(path, index=False)
        slice_paths[column] = str(path)

    summary_path = output_dir / f"{group_column}_summary.md"
    _write_markdown_summary(
        summary_path,
        group_column=group_column,
        model_name=model_name,
        predictions=enriched,
        group_table=group_table,
        blend_table=blend_table,
    )
    return {
        "group_column": group_column,
        "rows": int(len(enriched)),
        "groups": int(enriched["holdout_group"].nunique()),
        "outputs": {
            "predictions": str(output_dir / f"{group_column}_holdout_predictions.csv"),
            "group_brier_deltas": str(output_dir / f"{group_column}_brier_deltas.csv"),
            "local_router": str(output_dir / f"{group_column}_local_router.csv"),
            "prior_brier_deltas": str(output_dir / f"{group_column}_prior_brier_deltas.csv")
            if not prior_group_table.empty
            else None,
            "prior_fallback_audit": str(output_dir / f"{group_column}_prior_fallback_audit.json")
            if prior_audit
            else None,
            "prior_local_router": str(output_dir / f"{group_column}_prior_local_router.csv")
            if not prior_local_router_table.empty
            else None,
            "model_calibration_bins": str(output_dir / f"{group_column}_model_calibration_bins.csv"),
            "persistence_calibration_bins": str(
                output_dir / f"{group_column}_persistence_calibration_bins.csv"
            ),
            "blend_alpha_sweep": str(output_dir / f"{group_column}_blend_alpha_sweep.csv"),
            "summary": str(summary_path),
            "slices": slice_paths,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose spatial Brier failures by holdout group.")
    parser.add_argument("--curated-dir", type=Path, default=_repo_root() / "data" / "curated")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--model", default="hist_gbm")
    parser.add_argument("--group-columns", nargs="+", default=["county", "beach_id"])
    parser.add_argument("--training-window-days", type=int, default=365)
    parser.add_argument("--max-county-groups", type=int, default=12)
    parser.add_argument("--max-beach-groups", type=int, default=50)
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument("--alphas", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0")
    parser.add_argument("--stale-row-cutoffs", default="")
    parser.add_argument("--stale-censor-cutoffs", default="")
    args = parser.parse_args()

    output_dir = args.output_dir or (
        args.curated_dir / "diagnostics" / f"spatial_brier_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    features, labels, metadata = _prepare_inputs(
        args.curated_dir,
        training_window_days=args.training_window_days,
    )
    stv_threshold = get_settings().epa_marine_enterococcus_stv
    alphas = _parse_alphas(args.alphas)
    stale_cutoffs = _parse_ints(args.stale_censor_cutoffs) if args.stale_censor_cutoffs else []
    stale_row_cutoffs = (
        _parse_ints(args.stale_row_cutoffs) if args.stale_row_cutoffs else stale_cutoffs
    )

    manifest: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": args.model,
        "training_window_days": args.training_window_days,
        "groups": [],
        "stale_rows": [],
        "stale_censoring": [],
    }
    feature_variants = {"observed": features}
    feature_variants.update(build_stale_censoring_variants(features, cutoffs=stale_cutoffs))
    stale_row_manifests: list[dict[str, object]] = []

    for variant_label, variant_features in feature_variants.items():
        variant_group_manifests: list[dict[str, object]] = []
        variant_output_dir = output_dir if variant_label == "observed" else output_dir / variant_label
        for group_column in args.group_columns:
            if group_column == "county":
                min_rows = 32
                max_groups = args.max_county_groups
            elif group_column == "beach_id":
                min_rows = 8
                max_groups = args.max_beach_groups
            else:
                min_rows = 8
                max_groups = None

            predictions = _collect_holdout_predictions(
                variant_features,
                labels,
                metadata,
                group_column=group_column,
                model_name=args.model,
                stv_threshold=stv_threshold,
                min_rows=min_rows,
                max_groups=max_groups,
            )
            if predictions.empty:
                variant_group_manifests.append(
                    {"group_column": group_column, "rows": 0, "groups": 0, "outputs": {}}
                )
                continue
            group_manifest = _write_outputs(
                variant_output_dir,
                group_column=group_column,
                model_name=args.model,
                predictions=predictions,
                bins=args.bins,
                alphas=alphas,
            )
            group_manifest["variant"] = variant_label
            variant_group_manifests.append(group_manifest)

            if variant_label != "observed":
                continue
            for cutoff in stale_row_cutoffs:
                row_label = stale_row_label(cutoff)
                stale_predictions = filter_stale_rows(predictions, cutoff_days=cutoff)
                if stale_predictions.empty:
                    stale_row_manifests.append(
                        {
                            "variant": row_label,
                            "group_column": group_column,
                            "rows": 0,
                            "groups": 0,
                            "outputs": {},
                        }
                    )
                    continue
                stale_manifest = _write_outputs(
                    output_dir / "stale_rows" / row_label,
                    group_column=group_column,
                    model_name=args.model,
                    predictions=stale_predictions,
                    bins=args.bins,
                    alphas=alphas,
                )
                stale_manifest["variant"] = row_label
                stale_row_manifests.append(stale_manifest)

        if variant_label == "observed":
            manifest["groups"] = variant_group_manifests
            manifest["stale_rows"] = stale_row_manifests
            continue
        manifest["stale_censoring"].append(
            {
                "variant": variant_label,
                "groups": variant_group_manifests,
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"manifest": str(manifest_path), **manifest}, indent=2))


if __name__ == "__main__":
    main()
