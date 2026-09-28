from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)


ARTIFACT_TYPE = "t2d_rf_external_10group_v1"
RISK_COLUMN = "rf_external_10group_risk_5y"
RAW_RISK_COLUMN = f"{RISK_COLUMN}_raw"

CLINICAL_GROUP_DISPLAY = {
    "single::age_index": "Patient age at index",
    "single::age_start": "Patient age at earliest EHR record",
    "diagnosis::cvd_any": "Cardiovascular diagnosis (any CVD)",
    "single::months2index": "EHR history",
    "diagnosis::hypert": "Hypertension diagnosis",
    "rx::htn_diuretic": "Antihypertensive medication (diuretics)",
    "diagnosis::dm1": "Type 1 diabetes diagnosis",
    "category::Marital": "Marital status",
    "rx::lipid_statin": "Lipid-lowering medication (statins)",
    "diagnosis::obesity": "Obesity status",
}

SOURCE_TO_EXTERNAL = {
    "cardiovascularanyswd": "cvd_any",
    "cardiovascularanyswd_age": "cvd_any_age",
}
EXTERNAL_TO_SOURCE = {value: key for key, value in SOURCE_TO_EXTERNAL.items()}

FEATURE_GROUPS = {
    "single::age_index": ["age_index"],
    "single::age_start": ["age_start"],
    "diagnosis::cvd_any": [
        "cvd_any",
        "cvd_any_age",
    ],
    "single::months2index": ["months2index"],
    "diagnosis::hypert": ["hypert", "hypert_age"],
    "rx::htn_diuretic": [
        "rx_any_htn_diuretic",
        "rx_1y_htn_diuretic",
        "rx_dates1y_htn_diuretic",
        "rx_days_htn_diuretic",
        "rx_days_htn_diuretic_miss",
    ],
    "diagnosis::dm1": ["dm1", "dm1_age"],
    "category::Marital": ["Marital_1", "Marital_2", "Marital_3"],
    "rx::lipid_statin": [
        "rx_any_lipid_statin",
        "rx_1y_lipid_statin",
        "rx_dates1y_lipid_statin",
        "rx_days_lipid_statin",
        "rx_days_lipid_statin_miss",
    ],
    "diagnosis::obesity": ["obesity", "obesity_age"],
}

FEATURE_NAMES = [
    feature
    for group_features in FEATURE_GROUPS.values()
    for feature in group_features
]

BINARY_FEATURES = {
    "cvd_any",
    "hypert",
    "dm1",
    "Marital_1",
    "Marital_2",
    "Marital_3",
    "rx_any_htn_diuretic",
    "rx_1y_htn_diuretic",
    "rx_days_htn_diuretic_miss",
    "rx_any_lipid_statin",
    "rx_1y_lipid_statin",
    "rx_days_lipid_statin_miss",
    "obesity",
}

DIAGNOSIS_PAIRS = {
    "cvd_any": "cvd_any_age",
    "hypert": "hypert_age",
    "dm1": "dm1_age",
    "obesity": "obesity_age",
}

MEDICATION_CLASSES = ("htn_diuretic", "lipid_statin")


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix in {".csv", ".txt"}:
        return pd.read_csv(path)
    raise ValueError(f"Unsupported table type: {path}; use CSV or Parquet")


def write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".parquet", ".pq"}:
        frame.to_parquet(path, index=False)
    elif path.suffix.lower() == ".csv":
        frame.to_csv(path, index=False)
    else:
        raise ValueError(f"Unsupported output type: {path}; use CSV or Parquet")


def validate_predictors(frame: pd.DataFrame, strict: bool = True) -> list[str]:
    errors: list[str] = []
    missing = [name for name in FEATURE_NAMES if name not in frame]
    if missing:
        raise ValueError(f"Missing required predictors: {missing}")

    numeric = frame[FEATURE_NAMES].apply(pd.to_numeric, errors="coerce")
    nonfinite = [
        name
        for name in FEATURE_NAMES
        if numeric[name].isna().any()
        or not np.isfinite(numeric[name].to_numpy(float)).all()
    ]
    if nonfinite:
        errors.append(f"Missing or nonnumeric values in: {nonfinite}")

    for name in sorted(BINARY_FEATURES):
        bad = ~numeric[name].isin([0, 1])
        if bad.any():
            errors.append(f"{name} must contain only 0/1; bad rows={int(bad.sum())}")

    marital_sum = numeric[["Marital_1", "Marital_2", "Marital_3"]].sum(axis=1)
    if not (marital_sum == 1).all():
        errors.append(
            "Exactly one of Marital_1 (Married), Marital_2 (Single), and "
            f"Marital_3 (Unknown) must equal 1; bad rows={int((marital_sum != 1).sum())}"
        )

    for indicator, age_name in DIAGNOSIS_PAIRS.items():
        absent_bad = (numeric[indicator] == 0) & (numeric[age_name] != -1)
        present_bad = (numeric[indicator] == 1) & (
            (numeric[age_name] < 0) | (numeric[age_name] > numeric["age_index"])
        )
        if absent_bad.any() or present_bad.any():
            errors.append(
                f"{indicator}/{age_name} sentinel or timing inconsistency; "
                f"bad rows={int((absent_bad | present_bad).sum())}"
            )

    if (numeric["age_start"] > numeric["age_index"]).any():
        errors.append("age_start cannot exceed age_index")
    expected_months = (numeric["age_index"] - numeric["age_start"]) * 12.0
    timing_difference = np.abs(numeric["months2index"] - expected_months)
    if (timing_difference > 0.2).any():
        errors.append(
            "months2index is inconsistent with age_index and age_start by >0.2 months "
            f"in {int((timing_difference > 0.2).sum())} rows"
        )

    for med in MEDICATION_CLASSES:
        any_prior = numeric[f"rx_any_{med}"]
        any_1y = numeric[f"rx_1y_{med}"]
        dates_1y = numeric[f"rx_dates1y_{med}"]
        days = numeric[f"rx_days_{med}"]
        days_missing = numeric[f"rx_days_{med}_miss"]
        inconsistent = (
            ((any_prior == 0) & ((any_1y != 0) | (dates_1y != 0) | (days != -100) | (days_missing != 1)))
            | ((any_prior == 1) & ((days < 1) | (days_missing != 0)))
            | ((any_1y == 0) & (dates_1y != 0))
            | ((any_1y == 1) & ((dates_1y < 1) | (days > 365)))
            | (dates_1y < 0)
            | (dates_1y != np.floor(dates_1y))
        )
        if inconsistent.any():
            errors.append(
                f"Medication feature inconsistency for {med}; "
                f"bad rows={int(inconsistent.sum())}"
            )

    if errors and strict:
        raise ValueError("Predictor validation failed:\n- " + "\n- ".join(errors))
    return errors


def load_bundle(path: Path) -> dict:
    bundle = joblib.load(path)
    if not isinstance(bundle, dict) or bundle.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError(f"{path} is not a recognized {ARTIFACT_TYPE} bundle")
    if bundle.get("feature_names") != FEATURE_NAMES:
        raise ValueError("Model bundle feature order does not match the locked schema")
    return bundle


def weighted_censoring_km(
    time: np.ndarray,
    event: np.ndarray,
    weight: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    time = np.asarray(time, dtype=float)
    event = np.asarray(event, dtype=bool)
    weight = np.ones(len(time), dtype=float) if weight is None else np.asarray(weight, float)
    valid = np.isfinite(time) & np.isfinite(weight) & (weight > 0)
    time, event, weight = time[valid], event[valid], weight[valid]
    order = np.argsort(time, kind="mergesort")
    time, event, weight = time[order], event[order], weight[order]
    unique, starts = np.unique(time, return_index=True)
    risk = weight.sum()
    before, after = [], []
    survival = 1.0
    for index, start in enumerate(starts):
        stop = starts[index + 1] if index + 1 < len(starts) else len(time)
        before.append(survival)
        censor_weight = weight[start:stop][~event[start:stop]].sum()
        if risk > 0:
            survival *= max(0.0, 1.0 - censor_weight / risk)
        after.append(survival)
        risk -= weight[start:stop].sum()
    return unique, np.asarray(before), np.asarray(after)


def km_lookup(query: np.ndarray, times: np.ndarray, values: np.ndarray) -> np.ndarray:
    query = np.atleast_1d(np.asarray(query, float))
    indices = np.searchsorted(times, query, side="right") - 1
    output = np.ones(len(query), dtype=float)
    valid = indices >= 0
    output[valid] = values[indices[valid]]
    return np.clip(output, 1e-6, 1.0)


def horizon_data(
    event: np.ndarray,
    time: np.ndarray,
    horizon: float,
    censoring_km: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    event = np.asarray(event, bool)
    time = np.asarray(time, float)
    positive = event & (time <= horizon)
    observed_negative = time >= horizon
    eligible = positive | observed_negative
    y = positive.astype(np.uint8)
    if censoring_km is None:
        censoring_km = weighted_censoring_km(time, event)
    km_time, km_before, km_after = censoring_km
    weight = np.zeros(len(time), dtype=float)
    weight[positive] = 1.0 / km_lookup(time[positive], km_time, km_before)
    g_horizon = float(km_lookup(np.asarray([horizon]), km_time, km_after)[0])
    weight[observed_negative] = 1.0 / g_horizon
    return y, weight, eligible


def weighted_metrics(y: np.ndarray, risk: np.ndarray, weight: np.ndarray) -> dict:
    keep = np.isfinite(risk) & np.isfinite(weight) & (weight > 0)
    y, risk, weight = y[keep], risk[keep], weight[keep]
    return {
        "n": int(len(y)),
        "events": int(y.sum()),
        "weighted_event_fraction": float(np.average(y, weights=weight)),
        "mean_predicted_risk": float(np.average(risk, weights=weight)),
        "roc_auc": float(roc_auc_score(y, risk, sample_weight=weight)),
        "average_precision": float(
            average_precision_score(y, risk, sample_weight=weight)
        ),
        "brier": float(brier_score_loss(y, risk, sample_weight=weight)),
    }


def calibration_metrics(y: np.ndarray, risk: np.ndarray, weight: np.ndarray) -> dict:
    y = np.asarray(y)
    risk = np.asarray(risk, dtype=float)
    weight = np.asarray(weight, dtype=float)
    keep = np.isfinite(risk) & np.isfinite(weight) & (weight > 0)
    y, risk, weight = y[keep], np.clip(risk[keep], 1e-6, 1 - 1e-6), weight[keep]
    logit = np.log(risk / (1.0 - risk)).reshape(-1, 1)
    model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=1000)
    model.fit(logit, y, sample_weight=weight)
    observed = float(np.average(y, weights=weight))
    predicted = float(np.average(risk, weights=weight))
    return {
        "calibration_intercept": float(model.intercept_[0]),
        "calibration_slope": float(model.coef_[0, 0]),
        "observed_to_expected_ratio": observed / max(predicted, 1e-12),
    }


def weighted_calibration_table(
    y: np.ndarray,
    risk: np.ndarray,
    weight: np.ndarray,
    bins: int = 10,
) -> pd.DataFrame:
    frame = pd.DataFrame({"y": y, "risk": risk, "weight": weight})
    frame = frame[np.isfinite(frame.risk) & np.isfinite(frame.weight) & (frame.weight > 0)]
    order = np.argsort(frame.risk.to_numpy(), kind="mergesort")
    frame = frame.iloc[order].reset_index(drop=True)
    cumulative = frame.weight.cumsum() / frame.weight.sum()
    frame["bin"] = np.minimum((cumulative * bins).astype(int), bins - 1) + 1
    rows = []
    for bin_id, part in frame.groupby("bin", sort=True):
        rows.append({
            "bin": int(bin_id),
            "n": int(len(part)),
            "weighted_n": float(part.weight.sum()),
            "mean_predicted": float(np.average(part.risk, weights=part.weight)),
            "observed_fraction": float(np.average(part.y, weights=part.weight)),
            "minimum_predicted": float(part.risk.min()),
            "maximum_predicted": float(part.risk.max()),
        })
    return pd.DataFrame(rows)


def save_json(value: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")


def curve_data(y: np.ndarray, risk: np.ndarray, weight: np.ndarray) -> dict:
    false_positive, true_positive, roc_threshold = roc_curve(y, risk, sample_weight=weight)
    precision, recall, pr_threshold = precision_recall_curve(y, risk, sample_weight=weight)
    return {
        "roc": pd.DataFrame({
            "false_positive_rate": false_positive,
            "true_positive_rate": true_positive,
            "threshold": roc_threshold,
        }),
        "pr": pd.DataFrame({
            "recall": recall,
            "precision": precision,
            "threshold": np.r_[pr_threshold, np.nan],
        }),
    }
