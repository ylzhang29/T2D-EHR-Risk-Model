from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from external_rf_common import (
    FEATURE_NAMES, MODEL_VARIANTS, RAW_RISK_COLUMNS, RISK_COLUMNS,
    apply_logistic_calibration, load_bundle, read_table, validate_predictors,
    write_table,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score one or both frozen T1D-excluded EHR models")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--model-variant", action="append", choices=MODEL_VARIANTS, required=True)
    parser.add_argument("--batch-size", type=int, default=100_000)
    args = parser.parse_args()
    variants = list(dict.fromkeys(args.model_variant))
    frame = read_table(args.input)
    validate_predictors(frame, variants, strict=True)
    for variant in variants:
        path = args.model_dir / ("compact_5group_5y_bundle.joblib" if variant == "compact5" else "compact_10group_5y_bundle.joblib")
        bundle = load_bundle(path, variant)
        raw_parts = []
        for start in range(0, len(frame), args.batch_size):
            matrix = frame.iloc[start:start + args.batch_size][FEATURE_NAMES[variant]].astype(np.float32)
            raw_parts.append(bundle["model"].predict_proba(matrix)[:, 1])
        raw = np.concatenate(raw_parts) if raw_parts else np.array([], float)
        frame[RAW_RISK_COLUMNS[variant]] = raw
        frame[RISK_COLUMNS[variant]] = apply_logistic_calibration(raw, bundle["calibration"])
        print(f"{variant}: applied frozen natural-validation logistic calibration")
    write_table(frame, args.output)
    print(f"Scored {len(frame):,} rows for: {', '.join(variants)}")


if __name__ == "__main__":
    main()
