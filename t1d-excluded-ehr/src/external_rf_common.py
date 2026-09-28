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


PACKAGE_VERSION = "4.0"
HORIZON_YEARS = 5.0
MODEL_VARIANTS = ("compact5", "compact10")
MODEL_FILES = {
    "compact5": "compact_5group_5y_bundle.joblib",
    "compact10": "compact_10group_5y_bundle.joblib",
}
RISK_COLUMNS = {
    variant: f"{variant}_transported_risk_5y" for variant in MODEL_VARIANTS
}
RAW_RISK_COLUMNS = {variant: f"{variant}_raw_rf_probability" for variant in MODEL_VARIANTS}

FEATURE_GROUPS = {
    "compact5": {
        "diagnosis::depress": ["depress", "depress_age"],
        "diagnosis::obesity": ["obesity", "obesity_age"],
        "rx::lipid_statin": [
            "rx_any_lipid_statin", "rx_1y_lipid_statin",
            "rx_dates1y_lipid_statin", "rx_days_lipid_statin",
            "rx_days_lipid_statin_miss",
        ],
        "rx::mood_antiep": [
            "rx_any_mood_antiep", "rx_1y_mood_antiep",
            "rx_dates1y_mood_antiep", "rx_days_mood_antiep",
            "rx_days_mood_antiep_miss",
        ],
        "single::age_index": ["age_index"],
    },
    "compact10": {
        "diagnosis::PDD": ["PDD", "PDD_age"],
        "diagnosis::gestationaldm": ["gestationaldm", "gestationaldm_age"],
        "diagnosis::hf": ["hf", "hf_age"],
        "diagnosis::obesity": ["obesity", "obesity_age"],
        "diagnosis::sleep": ["sleep", "sleep_age"],
        "rx::mood_antiep": [
            "rx_any_mood_antiep", "rx_1y_mood_antiep",
            "rx_dates1y_mood_antiep", "rx_days_mood_antiep",
            "rx_days_mood_antiep_miss",
        ],
        "single::age_index": ["age_index"],
        "single::age_start": ["age_start"],
        "single::months2index": ["months2index"],
        "single::smoking_proxy_diagnosis": ["smoking_proxy_diagnosis"],
    },
}
FEATURE_NAMES = {
    variant: [feature for features in groups.values() for feature in features]
    for variant, groups in FEATURE_GROUPS.items()
}
UNION_FEATURE_NAMES = list(dict.fromkeys(FEATURE_NAMES["compact5"] + FEATURE_NAMES["compact10"]))

DIAGNOSIS_PAIRS = {
    "depress": "depress_age",
    "obesity": "obesity_age",
    "PDD": "PDD_age",
    "gestationaldm": "gestationaldm_age",
    "hf": "hf_age",
    "sleep": "sleep_age",
}
MEDICATION_CLASSES = ("lipid_statin", "mood_antiep")
BINARY_FEATURES = set(DIAGNOSIS_PAIRS) | {"smoking_proxy_diagnosis"}
for medication in MEDICATION_CLASSES:
    BINARY_FEATURES.update({
        f"rx_any_{medication}", f"rx_1y_{medication}",
        f"rx_days_{medication}_miss",
    })


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if path.suffix.lower() in {".csv", ".txt"}:
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


def save_json(value: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def load_bundle(path: Path, variant: str) -> dict:
    if variant not in MODEL_VARIANTS:
        raise ValueError(f"Unknown model variant: {variant}")
    bundle = joblib.load(path)
    required = {"model", "features", "calibration"}
    if not isinstance(bundle, dict) or not required.issubset(bundle):
        raise ValueError(f"{path} is not a recognized frozen T1D-excluded EHR bundle")
    if list(bundle["features"]) != FEATURE_NAMES[variant]:
        raise ValueError(f"{variant} bundle feature order does not match its contract")
    model_features = list(getattr(bundle["model"], "feature_names_in_", []))
    if model_features and model_features != FEATURE_NAMES[variant]:
        raise ValueError(f"{variant} estimator feature_names_in_ does not match its contract")
    calibration = bundle["calibration"]
    if float(calibration.get("horizon_years", -1)) != HORIZON_YEARS:
        raise ValueError(f"{variant} bundle has the wrong prediction horizon")
    if "validation" not in str(calibration.get("fit_source", "")).lower():
        raise ValueError(f"{variant} calibration provenance is not natural validation")
    return bundle


def validate_predictors(frame: pd.DataFrame, variants: list[str], strict: bool = True) -> list[str]:
    features = list(dict.fromkeys(name for variant in variants for name in FEATURE_NAMES[variant]))
    missing = [name for name in features if name not in frame]
    if missing:
        raise ValueError(f"Missing required predictors: {missing}")
    numeric = frame[features].apply(pd.to_numeric, errors="coerce")
    errors: list[str] = []
    bad_numeric = [
        name for name in features
        if numeric[name].isna().any() or not np.isfinite(numeric[name].to_numpy(float)).all()
    ]
    if bad_numeric:
        errors.append(f"Missing, nonnumeric, or infinite values in: {bad_numeric}")
    for name in sorted(BINARY_FEATURES.intersection(features)):
        bad = ~numeric[name].isin([0, 1])
        if bad.any():
            errors.append(f"{name} must contain only 0/1; bad rows={int(bad.sum())}")
    for indicator, age_name in DIAGNOSIS_PAIRS.items():
        if indicator not in features or age_name not in features:
            continue
        absent_bad = (numeric[indicator] == 0) & (numeric[age_name] != -1)
        present_bad = (numeric[indicator] == 1) & (
            (numeric[age_name] < 0) | (numeric[age_name] > numeric["age_index"])
        )
        if (absent_bad | present_bad).any():
            errors.append(
                f"{indicator}/{age_name} sentinel or timing inconsistency; "
                f"bad rows={int((absent_bad | present_bad).sum())}"
            )
    if "age_start" in features:
        bad = numeric.age_start > numeric.age_index
        if bad.any():
            errors.append(f"age_start cannot exceed age_index; bad rows={int(bad.sum())}")
    if "months2index" in features:
        bad = numeric.months2index < 0
        if bad.any():
            errors.append(f"months2index must be nonnegative; bad rows={int(bad.sum())}")
        if "age_start" in features:
            delta = np.abs(numeric.months2index - (numeric.age_index - numeric.age_start) * 12)
            if (delta > 0.2).any():
                errors.append(
                    "months2index is inconsistent with age_index and age_start by >0.2 "
                    f"months; bad rows={int((delta > 0.2).sum())}"
                )
    for med in MEDICATION_CLASSES:
        names = [f"rx_any_{med}", f"rx_1y_{med}", f"rx_dates1y_{med}",
                 f"rx_days_{med}", f"rx_days_{med}_miss"]
        if not set(names).issubset(features):
            continue
        any_prior, any_1y, dates, days, miss = (numeric[name] for name in names)
        bad = (
            ((any_prior == 0) & ((any_1y != 0) | (dates != 0) | (days != -100) | (miss != 1)))
            | ((any_prior == 1) & ((days < 1) | (miss != 0)))
            | ((any_1y == 0) & (dates != 0))
            | ((any_1y == 1) & ((dates < 1) | (days > 365)))
            | (dates < 0) | (dates != np.floor(dates))
        )
        if bad.any():
            errors.append(f"Medication feature inconsistency for {med}; bad rows={int(bad.sum())}")
    if errors and strict:
        raise ValueError("Predictor validation failed:\n- " + "\n- ".join(errors))
    return errors


def weighted_censoring_km(time: np.ndarray, event: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    time = np.asarray(time, float)
    event = np.asarray(event, bool)
    valid = np.isfinite(time) & (time > 0)
    time, event = time[valid], event[valid]
    order = np.argsort(time, kind="mergesort")
    time, event = time[order], event[order]
    unique, starts = np.unique(time, return_index=True)
    risk = float(len(time)); survival = 1.0; before = []; after = []
    for index, start in enumerate(starts):
        stop = starts[index + 1] if index + 1 < len(starts) else len(time)
        before.append(survival)
        censored = float((~event[start:stop]).sum())
        if risk > 0:
            survival *= max(0.0, 1.0 - censored / risk)
        after.append(survival)
        risk -= stop - start
    return unique, np.asarray(before), np.asarray(after)


def km_lookup(query: np.ndarray, times: np.ndarray, values: np.ndarray) -> np.ndarray:
    query = np.atleast_1d(np.asarray(query, float))
    indices = np.searchsorted(times, query, side="right") - 1
    output = np.ones(len(query), float)
    keep = indices >= 0
    output[keep] = values[indices[keep]]
    return np.clip(output, 1e-6, 1.0)


def horizon_data(event: np.ndarray, time: np.ndarray, horizon: float = HORIZON_YEARS) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    event = np.asarray(event, bool); time = np.asarray(time, float)
    positive = event & (time <= horizon)
    negative = time >= horizon
    eligible = positive | negative
    y = positive.astype(np.uint8)
    km_time, km_before, km_after = weighted_censoring_km(time, event)
    weight = np.zeros(len(time), float)
    weight[positive] = 1.0 / km_lookup(time[positive], km_time, km_before)
    weight[negative] = 1.0 / float(km_lookup(np.asarray([horizon]), km_time, km_after)[0])
    return y, weight, eligible


def weighted_metrics(y: np.ndarray, risk: np.ndarray, weight: np.ndarray) -> dict:
    return {
        "n": int(len(y)), "events": int(np.sum(y)),
        "weighted_event_fraction": float(np.average(y, weights=weight)),
        "mean_predicted_risk": float(np.average(risk, weights=weight)),
        "roc_auc": float(roc_auc_score(y, risk, sample_weight=weight)),
        "average_precision": float(average_precision_score(y, risk, sample_weight=weight)),
        "brier": float(brier_score_loss(y, risk, sample_weight=weight)),
    }


def fit_logistic_calibration(y: np.ndarray, risk: np.ndarray, weight: np.ndarray) -> dict:
    clipped = np.clip(np.asarray(risk, float), 1e-6, 1 - 1e-6)
    logit = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=2000)
    model.fit(logit, y, sample_weight=weight)
    return {"intercept": float(model.intercept_[0]), "slope": float(model.coef_[0, 0])}


def apply_logistic_calibration(risk: np.ndarray, calibration: dict) -> np.ndarray:
    clipped = np.clip(np.asarray(risk, float), 1e-6, 1 - 1e-6)
    logit = np.log(clipped / (1 - clipped))
    linear = float(calibration["intercept"]) + float(calibration["slope"]) * logit
    return 1.0 / (1.0 + np.exp(-linear))


def calibration_metrics(y: np.ndarray, risk: np.ndarray, weight: np.ndarray) -> dict:
    fit = fit_logistic_calibration(y, risk, weight)
    observed = float(np.average(y, weights=weight))
    predicted = float(np.average(risk, weights=weight))
    return {"calibration_intercept": fit["intercept"], "calibration_slope": fit["slope"],
            "observed_to_expected_ratio": observed / max(predicted, 1e-12)}


def weighted_calibration_table(y: np.ndarray, risk: np.ndarray, weight: np.ndarray, bins: int = 10) -> pd.DataFrame:
    frame = pd.DataFrame({"y": y, "risk": risk, "weight": weight}).sort_values("risk").reset_index(drop=True)
    cumulative = frame.weight.cumsum() / frame.weight.sum()
    frame["bin"] = np.minimum((cumulative * bins).astype(int), bins - 1) + 1
    rows = []
    for bin_id, part in frame.groupby("bin", sort=True):
        rows.append({"bin": int(bin_id), "n": int(len(part)),
                     "weighted_n": float(part.weight.sum()),
                     "mean_predicted": float(np.average(part.risk, weights=part.weight)),
                     "observed_fraction": float(np.average(part.y, weights=part.weight)),
                     "minimum_predicted": float(part.risk.min()),
                     "maximum_predicted": float(part.risk.max())})
    return pd.DataFrame(rows)


def curve_data(y: np.ndarray, risk: np.ndarray, weight: np.ndarray) -> dict[str, pd.DataFrame]:
    fpr, tpr, rt = roc_curve(y, risk, sample_weight=weight)
    precision, recall, pt = precision_recall_curve(y, risk, sample_weight=weight)
    return {
        "roc": pd.DataFrame({"false_positive_rate": fpr, "true_positive_rate": tpr, "threshold": rt}),
        "pr": pd.DataFrame({"recall": recall, "precision": precision, "threshold": np.r_[pt, np.nan]}),
    }
