from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from external_rf_common import (
    FEATURE_NAMES,
    RAW_RISK_COLUMN,
    RISK_COLUMN,
    load_bundle,
    read_table,
    validate_predictors,
    write_table,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate an external 24-predictor table and score the locked T2D RF"
    )
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=100_000)
    parser.add_argument(
        "--allow-uncalibrated",
        action="store_true",
        help=(
            "Allow a legacy bundle without frozen validation-fitted calibration. "
            "Use only for an explicitly labeled raw-model secondary analysis."
        ),
    )
    parser.add_argument(
        "--warnings-only",
        action="store_true",
        help="Print predictor consistency problems instead of stopping; not recommended.",
    )
    args = parser.parse_args()

    bundle = load_bundle(args.bundle)
    calibration = bundle.get("calibration")
    if calibration is None and not args.allow_uncalibrated:
        raise ValueError(
            "The model bundle has no frozen validation-fitted calibration. "
            "Provide the calibrated deployment bundle, or use "
            "--allow-uncalibrated only for a labeled raw-model analysis."
        )
    frame = read_table(args.input)
    problems = validate_predictors(frame, strict=not args.warnings_only)
    for problem in problems:
        print(f"WARNING: {problem}")

    model = bundle["model"]
    probabilities = []
    for start in range(0, len(frame), args.batch_size):
        stop = min(start + args.batch_size, len(frame))
        matrix = frame.iloc[start:stop][FEATURE_NAMES].astype(np.float32)
        probabilities.append(model.predict_proba(matrix)[:, 1].astype(np.float32))
    raw = np.concatenate(probabilities) if probabilities else np.array([], np.float32)
    frame[RAW_RISK_COLUMN] = raw
    if calibration is None:
        frame[RISK_COLUMN] = raw
        print("WARNING: scoring the uncalibrated legacy model")
    else:
        from scipy.special import expit, logit

        if calibration.get("method") != "IPCW-weighted logistic recalibration":
            raise ValueError(f"Unsupported calibration method: {calibration.get('method')}")
        intercept = float(calibration["intercept"])
        slope = float(calibration["slope"])
        if not np.isfinite(intercept) or not np.isfinite(slope) or slope <= 0:
            raise ValueError("Calibration intercept/slope are invalid")
        frame[RISK_COLUMN] = expit(
            intercept
            + slope * logit(np.clip(raw.astype(float), 1e-6, 1 - 1e-6))
        ).astype(np.float32)
        print(f"Applied frozen calibration: intercept={intercept:.6f}, slope={slope:.6f}")
    write_table(frame, args.output)
    print(f"Validated and scored {len(frame):,} rows")
    print(f"Raw prediction column: {RAW_RISK_COLUMN}")
    print(f"Primary prediction column: {RISK_COLUMN}")
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
