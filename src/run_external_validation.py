from __future__ import annotations

import argparse
import hashlib
import os
import platform
import subprocess
import sys
from pathlib import Path

import joblib
import matplotlib
import numpy as np
import pandas as pd
import pyarrow
import sklearn

from external_rf_common import FEATURE_NAMES, read_table, save_json, validate_predictors


def run(command: list[str], environment: dict[str, str]) -> None:
    print("\nRunning:", " ".join(command), flush=True)
    subprocess.run(command, check=True, env=environment)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build, validate, score, and evaluate the external T2D cohort in one run"
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument(
        "--final-input",
        type=Path,
        default=None,
        help=(
            "Site-prepared final table containing the locked 24 predictors, "
            "dm2, and event_years. Bypasses raw cohort/predictor construction."
        ),
    )
    parser.add_argument("--patients", type=Path, default=None)
    parser.add_argument("--encounters", type=Path, default=None)
    parser.add_argument("--non-adhd-random-seed", default=None)
    parser.add_argument("--diagnoses", type=Path, default=None)
    parser.add_argument("--medications", type=Path, default=None)
    parser.add_argument("--medication-lookup", type=Path, default=None)
    parser.add_argument(
        "--medication-code-system",
        choices=("auto", "atc", "rxnorm"),
        default="auto",
    )
    parser.add_argument("--phenotype-code-list", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bootstrap", type=int, default=500)
    parser.add_argument("--subgroups", default="sex,age_group")
    parser.add_argument("--decision-thresholds", default="")
    parser.add_argument(
        "--allow-uncalibrated",
        action="store_true",
        help="Run the legacy raw model only; not the primary external validation.",
    )
    args = parser.parse_args()

    raw_names = ("patients", "diagnoses", "medications", "medication_lookup")
    if args.final_input is None:
        missing = [name for name in raw_names if getattr(args, name) is None]
        if missing:
            raise ValueError(
                "Raw-input mode is missing: " + ", ".join(missing)
                + ". Alternatively supply --final-input."
            )
    else:
        supplied_raw = [name for name in raw_names if getattr(args, name) is not None]
        if supplied_raw or args.encounters is not None or args.phenotype_code_list is not None:
            raise ValueError(
                "--final-input cannot be combined with raw patients, encounters, "
                "diagnoses, medications, medication lookup, or phenotype code list"
            )
        if args.non_adhd_random_seed is not None:
            raise ValueError("--non-adhd-random-seed is not used with --final-input")

    script_dir = Path(__file__).resolve().parent
    args.output_dir.mkdir(parents=True, exist_ok=True)
    local_only = args.output_dir / "LOCAL_ONLY_DO_NOT_RETURN"
    return_dir = args.output_dir / "RETURN_TO_COORDINATING_CENTER"
    results = return_dir / "summary_results"
    local_only.mkdir(exist_ok=True)
    return_dir.mkdir(exist_ok=True)
    constructed = (
        args.final_input
        if args.final_input is not None
        else local_only / "external_model_input.parquet"
    )
    scored = local_only / "external_patient_scores.parquet"
    audit_json = return_dir / "external_model_input_audit.json"
    environment = dict(os.environ)
    mpl_cache = local_only / ".matplotlib"
    mpl_cache.mkdir(exist_ok=True)
    environment["MPLCONFIGDIR"] = str(mpl_cache)

    inputs = {"model": args.model}
    if args.final_input is not None:
        inputs["site_prepared_final_input"] = args.final_input
    else:
        inputs.update({
            "patients": args.patients,
            "diagnoses": args.diagnoses,
            "medications": args.medications,
            "medication_lookup": args.medication_lookup,
        })
    if args.phenotype_code_list is not None:
        inputs["phenotype_code_list"] = args.phenotype_code_list
    if args.encounters is not None:
        inputs["encounters"] = args.encounters
    model_bundle = joblib.load(args.model)
    calibration = model_bundle.get("calibration") if isinstance(model_bundle, dict) else None
    save_json({
        "input_files": {
            name: {"filename": path.name, "sha256": sha256(path)}
            for name, path in inputs.items()
        },
        "bootstrap_replicates": args.bootstrap,
        "subgroups": args.subgroups,
        "decision_thresholds": args.decision_thresholds,
        "input_mode": (
            "site_prepared_final_input" if args.final_input is not None
            else "raw_longitudinal_inputs"
        ),
        "medication_code_system": (
            None if args.final_input is not None else args.medication_code_system
        ),
        "landmark_mode": (
            "site_prepared_and_attested"
            if args.final_input is not None
            else ("pipeline_constructed" if args.encounters is not None else "site_preassigned")
        ),
        "non_adhd_random_seed": (
            str(args.non_adhd_random_seed) if args.encounters is not None else None
        ),
        "prediction_probability": (
            "validation-fitted logistic-calibrated 5-year risk"
            if calibration is not None
            else "legacy uncalibrated RF probability"
        ),
        "calibration": calibration,
        "allow_uncalibrated": bool(args.allow_uncalibrated),
        "patient_level_files_must_not_be_returned": [
            (
                args.final_input.name
                if args.final_input is not None
                else "external_model_input.parquet"
            ),
            "external_patient_scores.parquet",
        ],
        "software": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "pyarrow": pyarrow.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
            "matplotlib": matplotlib.__version__,
        },
        "return_directory": "RETURN_TO_COORDINATING_CENTER",
        "local_only_directory": "LOCAL_ONLY_DO_NOT_RETURN",
    }, return_dir / "run_manifest.json")

    if args.final_input is None:
        build_command = [
            sys.executable,
            str(script_dir / "build_external_model_input.py"),
            "--patients", str(args.patients),
            "--diagnoses", str(args.diagnoses),
            "--medications", str(args.medications),
            "--medication-lookup", str(args.medication_lookup),
            "--medication-code-system", args.medication_code_system,
            "--output", str(constructed),
            "--audit-json", str(audit_json),
        ]
        if args.encounters is not None:
            if args.non_adhd_random_seed is None:
                raise ValueError("--encounters requires --non-adhd-random-seed")
            build_command.extend([
                "--encounters", str(args.encounters),
                "--non-adhd-random-seed", str(args.non_adhd_random_seed),
            ])
        if args.phenotype_code_list is not None:
            build_command.extend(["--phenotype-code-list", str(args.phenotype_code_list)])
        run(build_command, environment)
    else:
        final = read_table(args.final_input)
        problems = validate_predictors(final, strict=True)
        required_final = {"patient_id", "dm2", "event_years"}
        missing_final = sorted(required_final - set(final.columns))
        if missing_final:
            raise ValueError(f"Final input is missing required columns: {missing_final}")
        if final.patient_id.isna().any() or final.patient_id.astype(str).duplicated().any():
            raise ValueError("Final input patient_id must be complete and unique")
        if not set(final.dm2.dropna().unique()).issubset({0, 1}):
            raise ValueError("Final input dm2 must contain only 0/1")
        event_years = pd.to_numeric(final.event_years, errors="coerce")
        if event_years.isna().any() or (event_years <= 0).any():
            raise ValueError("Final input event_years must be complete and >0")
        audit = {
            "input_mode": "site_prepared_final_input",
            "site_attestation_required": True,
            "patients_input": int(len(final)),
            "patients_output": int(len(final)),
            "events": int(pd.to_numeric(final.dm2).sum()),
            "predictor_columns": FEATURE_NAMES,
            "predictor_validation_problems": problems,
            "patient_id_complete_and_unique": True,
            "dm2_binary": True,
            "event_years_complete_and_positive": True,
            "optional_subgroup_columns_present": [
                name for name in ("cohort", "sex", "age_group") if name in final
            ],
            "construction_not_reaudited": (
                "The package validated the final schema and values but did not "
                "reconstruct landmarks, predictors, outcome, or censoring from raw data."
            ),
        }
        save_json(audit, audit_json)

    score_command = [
        sys.executable,
        str(script_dir / "score_saved_model.py"),
        "--bundle", str(args.model),
        "--input", str(constructed),
        "--output", str(scored),
    ]
    if args.allow_uncalibrated:
        score_command.append("--allow-uncalibrated")
    run(score_command, environment)

    evaluate_command = [
        sys.executable,
        str(script_dir / "evaluate_external_validation.py"),
        "--input", str(scored),
        "--output-dir", str(results),
        "--bootstrap", str(args.bootstrap),
        "--subgroups", args.subgroups,
    ]
    if args.decision_thresholds:
        evaluate_command.extend(["--decision-thresholds", args.decision_thresholds])
    run(evaluate_command, environment)

    print("\nExternal validation completed successfully.")
    print(f"LOCAL ONLY — do not return: {local_only}")
    print(f"SAFE RETURN DIRECTORY: {return_dir}")


if __name__ == "__main__":
    main()
