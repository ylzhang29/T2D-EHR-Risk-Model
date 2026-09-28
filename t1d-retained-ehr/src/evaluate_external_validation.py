from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from external_rf_common import (
    RAW_RISK_COLUMN,
    RISK_COLUMN,
    calibration_metrics,
    curve_data,
    horizon_data,
    read_table,
    save_json,
    weighted_calibration_table,
    weighted_metrics,
)


METRIC_NAMES = (
    "roc_auc",
    "average_precision",
    "brier",
    "calibration_intercept",
    "calibration_slope",
    "observed_to_expected_ratio",
)


def parse_thresholds(value: str) -> np.ndarray:
    if not value.strip():
        return np.array([], dtype=float)
    thresholds = np.array([float(item) for item in value.split(",")], dtype=float)
    if np.any((thresholds <= 0) | (thresholds >= 1)):
        raise ValueError("Every decision threshold must be strictly between 0 and 1")
    return np.unique(thresholds)


def evaluate_frame(
    frame: pd.DataFrame,
    horizon: float,
    risk_column: str = RISK_COLUMN,
) -> tuple[dict, pd.DataFrame]:
    y, weight, eligible = horizon_data(
        frame.dm2.to_numpy(bool),
        frame.event_years.to_numpy(float),
        horizon,
    )
    evaluated = frame.loc[eligible].reset_index(drop=True).copy()
    y, weight = y[eligible], weight[eligible]
    risk = evaluated[risk_column].to_numpy(float)
    metrics = weighted_metrics(y, risk, weight)
    metrics.update(calibration_metrics(y, risk, weight))
    evaluated["horizon_outcome"] = y
    evaluated["ipcw"] = weight
    return metrics, evaluated


def bootstrap_metrics(
    frame: pd.DataFrame,
    horizon: float,
    replicates: int,
    seed: int,
) -> pd.DataFrame:
    if replicates <= 0:
        return pd.DataFrame()
    rng = np.random.default_rng(seed)
    rows = []
    n = len(frame)
    for replicate in range(replicates):
        indices = rng.integers(0, n, size=n)
        sample = frame.iloc[indices].reset_index(drop=True)
        try:
            metrics, _ = evaluate_frame(sample, horizon)
            rows.append({"replicate": replicate, **{name: metrics[name] for name in METRIC_NAMES}})
        except ValueError:
            continue
        if (replicate + 1) % 50 == 0:
            print(f"Bootstrap {replicate + 1}/{replicates}", flush=True)
    return pd.DataFrame(rows)


def confidence_intervals(point: dict, bootstrap: pd.DataFrame) -> dict:
    output = {}
    for metric in METRIC_NAMES:
        entry = {"estimate": float(point[metric])}
        if metric in bootstrap and len(bootstrap):
            values = bootstrap[metric].dropna().to_numpy(float)
            if len(values):
                entry.update({
                    "ci_95_lower": float(np.quantile(values, 0.025)),
                    "ci_95_upper": float(np.quantile(values, 0.975)),
                    "bootstrap_replicates_valid": int(len(values)),
                })
        output[metric] = entry
    return output


def decision_tables(
    evaluated: pd.DataFrame,
    thresholds: np.ndarray,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if len(thresholds) == 0:
        return pd.DataFrame(), pd.DataFrame()
    y = evaluated.horizon_outcome.to_numpy(bool)
    risk = evaluated[RISK_COLUMN].to_numpy(float)
    weight = evaluated.ipcw.to_numpy(float)
    total = weight.sum()
    prevalence = float(np.sum(weight * y) / total)
    dca_rows, impact_rows = [], []
    for threshold in thresholds:
        positive = risk >= threshold
        true_positive = float(weight[positive & y].sum())
        false_positive = float(weight[positive & ~y].sum())
        high_risk = float(weight[positive].sum())
        odds = threshold / (1.0 - threshold)
        dca_rows.append({
            "threshold": threshold,
            "net_benefit_model": true_positive / total - false_positive / total * odds,
            "net_benefit_treat_all": prevalence - (1.0 - prevalence) * odds,
            "net_benefit_treat_none": 0.0,
        })
        impact_rows.append({
            "threshold": threshold,
            "high_risk_per_1000": high_risk / total * 1000.0,
            "true_positives_per_1000": true_positive / total * 1000.0,
        })
    return pd.DataFrame(dca_rows), pd.DataFrame(impact_rows)


def subgroup_metrics(frame: pd.DataFrame, columns: list[str], horizon: float) -> pd.DataFrame:
    rows = []
    for column in columns:
        if column not in frame:
            print(f"WARNING: subgroup column not found and skipped: {column}")
            continue
        for level, part in frame.groupby(column, dropna=False):
            if len(part) < 100:
                continue
            try:
                metric, _ = evaluate_frame(part.reset_index(drop=True), horizon)
            except ValueError:
                continue
            rows.append({"subgroup_variable": column, "level": str(level), **metric})
    return pd.DataFrame(rows)


def make_plots(
    output_dir: Path,
    evaluated: pd.DataFrame,
    calibration: pd.DataFrame,
    dca: pd.DataFrame,
    impact: pd.DataFrame,
    file_prefix: str,
) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    y = evaluated.horizon_outcome.to_numpy(int)
    risk = evaluated[RISK_COLUMN].to_numpy(float)
    weight = evaluated.ipcw.to_numpy(float)
    curves = curve_data(y, risk, weight)
    curves["roc"].to_csv(output_dir / f"{file_prefix}_roc_curve.csv", index=False)
    curves["pr"].to_csv(output_dir / f"{file_prefix}_pr_curve.csv", index=False)

    figure, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    axes[0].plot(curves["roc"].false_positive_rate, curves["roc"].true_positive_rate)
    axes[0].plot([0, 1], [0, 1], color="grey", linestyle="--")
    axes[0].set(xlabel="False-positive rate", ylabel="True-positive rate", title="ROC curve")

    axes[1].plot(curves["pr"].recall, curves["pr"].precision)
    axes[1].set(xlabel="Recall", ylabel="Precision", title="Precision-recall curve")

    axes[2].plot(calibration.mean_predicted, calibration.observed_fraction, marker="o")
    axes[2].plot([0, 1], [0, 1], color="grey", linestyle="--")
    maximum = max(float(calibration.mean_predicted.max()), float(calibration.observed_fraction.max()))
    axes[2].set_xlim(0, min(1.0, maximum * 1.15))
    axes[2].set_ylim(0, min(1.0, maximum * 1.15))
    axes[2].set(xlabel="Mean predicted risk", ylabel="Observed 5-year risk", title="Calibration")
    figure.tight_layout()
    figure.savefig(
        output_dir / f"{file_prefix}_discrimination_calibration.png",
        dpi=300,
        bbox_inches="tight",
    )
    plt.close(figure)

    if len(dca):
        figure, axes = plt.subplots(1, 2, figsize=(11, 4.5))
        axes[0].plot(dca.threshold, dca.net_benefit_model, label="Model")
        axes[0].plot(dca.threshold, dca.net_benefit_treat_all, label="Treat all", linestyle="--")
        axes[0].plot(dca.threshold, dca.net_benefit_treat_none, label="Treat none", linestyle=":")
        axes[0].set(xlabel="Risk threshold", ylabel="Net benefit", title="Decision-curve analysis")
        axes[0].legend(frameon=False)
        axes[1].plot(impact.threshold, impact.high_risk_per_1000, label="Classified high risk")
        axes[1].plot(impact.threshold, impact.true_positives_per_1000, label="True positives")
        axes[1].set(xlabel="Risk threshold", ylabel="Patients per 1,000", title="Clinical impact curve")
        axes[1].legend(frameon=False)
        figure.tight_layout()
        figure.savefig(
            output_dir / f"{file_prefix}_dca_clinical_impact.png",
            dpi=300,
            bbox_inches="tight",
        )
        plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate locked 5-year RF predictions in an external cohort"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--horizon", type=float, default=5.0)
    parser.add_argument("--bootstrap", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260322)
    parser.add_argument("--file-prefix", default="external")
    parser.add_argument("--evaluation-label", default="external cohort")
    parser.add_argument(
        "--subgroups",
        default="",
        help="Optional comma-separated columns, for example cohort,sex,age_group.",
    )
    parser.add_argument(
        "--decision-thresholds",
        default="",
        help="Prespecified comma-separated clinical thresholds; DCA/CIC are skipped if omitted.",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    frame = read_table(args.input)
    required = ["dm2", "event_years", RISK_COLUMN]
    missing = [name for name in required if name not in frame]
    if missing:
        raise ValueError(f"External scored table is missing: {missing}")
    if not frame.dm2.isin([0, 1, False, True]).all():
        raise ValueError("dm2 must contain only 0/1")
    if frame.event_years.isna().any() or (frame.event_years <= 0).any():
        raise ValueError("event_years must be finite and >0 for every patient")
    if frame[RISK_COLUMN].isna().any() or not frame[RISK_COLUMN].between(0, 1).all():
        raise ValueError(f"{RISK_COLUMN} must be complete and between 0 and 1")

    metrics, evaluated = evaluate_frame(frame, args.horizon)
    raw_metrics = None
    raw_calibration = pd.DataFrame()
    if RAW_RISK_COLUMN in frame:
        raw_metrics, raw_evaluated = evaluate_frame(
            frame, args.horizon, risk_column=RAW_RISK_COLUMN
        )
        raw_calibration = weighted_calibration_table(
            raw_evaluated.horizon_outcome.to_numpy(int),
            raw_evaluated[RAW_RISK_COLUMN].to_numpy(float),
            raw_evaluated.ipcw.to_numpy(float),
        )
    bootstrap = bootstrap_metrics(frame, args.horizon, args.bootstrap, args.seed)
    intervals = confidence_intervals(metrics, bootstrap)
    calibration = weighted_calibration_table(
        evaluated.horizon_outcome.to_numpy(int),
        evaluated[RISK_COLUMN].to_numpy(float),
        evaluated.ipcw.to_numpy(float),
    )
    thresholds = parse_thresholds(args.decision_thresholds)
    dca, impact = decision_tables(evaluated, thresholds)
    subgroup_columns = [item.strip() for item in args.subgroups.split(",") if item.strip()]
    subgroups = subgroup_metrics(frame, subgroup_columns, args.horizon)

    result = {
        "model": "locked external 10-group RF",
        "horizon_years": args.horizon,
        "evaluation_source": args.evaluation_label,
        "censoring_weights_reference": args.evaluation_label,
        "early_censored_before_horizon_excluded_from_binary_horizon_metrics": True,
        "metrics": metrics,
        "raw_model_secondary_metrics": raw_metrics,
        "confidence_intervals": intervals,
        "bootstrap_replicates_requested": args.bootstrap,
        "bootstrap_replicates_valid": int(len(bootstrap)),
        "decision_thresholds": thresholds.tolist(),
    }
    prefix = args.file_prefix
    save_json(result, args.output_dir / f"{prefix}_metrics.json")
    # Patient-level predictions are deliberately not written inside
    # summary_results. The scored table remains local in the parent output
    # directory and must not be returned without separate authorization.
    bootstrap.to_csv(args.output_dir / f"{prefix}_bootstrap_metrics.csv", index=False)
    calibration.to_csv(args.output_dir / f"{prefix}_calibration.csv", index=False)
    if len(raw_calibration):
        raw_calibration.to_csv(
            args.output_dir / f"{prefix}_raw_model_calibration.csv", index=False
        )
    if len(dca):
        dca.to_csv(args.output_dir / f"{prefix}_decision_curve.csv", index=False)
        impact.to_csv(args.output_dir / f"{prefix}_clinical_impact.csv", index=False)
    if len(subgroups):
        subgroups.to_csv(args.output_dir / f"{prefix}_subgroup_metrics.csv", index=False)
    make_plots(args.output_dir, evaluated, calibration, dca, impact, prefix)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
