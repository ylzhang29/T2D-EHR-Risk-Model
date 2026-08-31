from __future__ import annotations

import argparse
import ast
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

import joblib


ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "model/rf_external_10group_5y_calibrated.joblib"
EXPECTED_ARTIFACT = "t2d_rf_external_10group_v1"
EXPECTED_FEATURES = [
    "age_index", "age_start", "cvd_any", "cvd_any_age", "months2index",
    "hypert", "hypert_age", "rx_any_htn_diuretic", "rx_1y_htn_diuretic",
    "rx_dates1y_htn_diuretic", "rx_days_htn_diuretic",
    "rx_days_htn_diuretic_miss", "dm1", "dm1_age", "Marital_1",
    "Marital_2", "Marital_3", "rx_any_lipid_statin",
    "rx_1y_lipid_statin", "rx_dates1y_lipid_statin",
    "rx_days_lipid_statin", "rx_days_lipid_statin_miss", "obesity",
    "obesity_age",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_checksums() -> None:
    checksum_file = ROOT / "PACKAGE_SHA256SUMS.txt"
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(maxsplit=1)
        clean_relative = relative[2:] if relative.startswith("./") else relative
        path = ROOT / clean_relative
        if not path.is_file():
            raise FileNotFoundError(f"Package file is missing: {relative}")
        observed = sha256(path)
        if observed != expected:
            raise ValueError(f"Checksum mismatch: {relative}")
    print("[OK] All package checksums match")


def verify_python() -> None:
    scripts = sorted((ROOT / "src").glob("*.py"))
    if not scripts:
        raise FileNotFoundError("No Python scripts found in src")
    for script in scripts:
        ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
    print(f"[OK] Python syntax parsed for {len(scripts)} scripts")


def verify_model() -> None:
    bundle = joblib.load(MODEL)
    if not isinstance(bundle, dict):
        raise TypeError("Deployment model is not the expected bundle dictionary")
    if bundle.get("artifact_type") != EXPECTED_ARTIFACT:
        raise ValueError("Unexpected model artifact type")
    if list(bundle.get("feature_names", [])) != EXPECTED_FEATURES:
        raise ValueError("Model feature names/order do not match the locked contract")
    model = bundle.get("model")
    if model is None or not hasattr(model, "predict_proba"):
        raise ValueError("Saved RF estimator is missing or cannot predict probabilities")
    calibration = bundle.get("calibration")
    if not isinstance(calibration, dict) or not calibration.get("locked_before_external_outcomes"):
        raise ValueError("Frozen external calibration is missing or not locked")
    if float(bundle.get("horizon_years")) != 5.0:
        raise ValueError("Unexpected model horizon")
    print("[OK] Calibrated saved RF loaded successfully")
    print(f"     Model class: {type(model).__module__}.{type(model).__name__}")
    print(f"     Predictors: {len(EXPECTED_FEATURES)}")
    print("     Horizon: 5 years")
    print(f"     Model SHA-256: {sha256(MODEL)}")


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def synthetic_tests() -> None:
    script = ROOT / "src/run_external_validation.py"
    examples = ROOT / "examples"
    definitions = ROOT / "definitions"
    thresholds = "0.005,0.01,0.02,0.03,0.05,0.075,0.10"
    with tempfile.TemporaryDirectory(prefix="t2d_external_validation_") as temp:
        temp_root = Path(temp)
        run([
            sys.executable, str(script),
            "--model", str(MODEL),
            "--patients", str(examples / "synthetic_raw_patients.csv"),
            "--encounters", str(examples / "synthetic_raw_encounters.csv"),
            "--non-adhd-random-seed", "EXAMPLE-SITE-SEED-2026",
            "--diagnoses", str(examples / "synthetic_raw_diagnoses.csv"),
            "--phenotype-code-list", str(definitions / "phenotype_code_list_REQUIRED.csv"),
            "--medications", str(examples / "synthetic_raw_medications_atc.csv"),
            "--medication-lookup", str(definitions / "external_atc_medication_lookup.csv"),
            "--medication-code-system", "atc",
            "--output-dir", str(temp_root / "raw_mode"),
            "--bootstrap", "0",
            "--subgroups", "sex,age_group",
            "--decision-thresholds", thresholds,
        ])
        run([
            sys.executable, str(script),
            "--model", str(MODEL),
            "--final-input", str(examples / "synthetic_site_prepared_final_input.csv"),
            "--output-dir", str(temp_root / "final_input_mode"),
            "--bootstrap", "0",
            "--subgroups", "sex,age_group",
            "--decision-thresholds", thresholds,
        ])
        run([
            sys.executable, str(script),
            "--model", str(MODEL),
            "--patients", str(examples / "example_patient_shell.csv"),
            "--diagnoses", str(examples / "example_diagnoses_mapped.csv"),
            "--medications", str(examples / "example_medications_atc.csv"),
            "--medication-lookup", str(definitions / "external_atc_medication_lookup.csv"),
            "--medication-code-system", "atc",
            "--output-dir", str(temp_root / "no_encounter_mode"),
            "--bootstrap", "0",
            "--subgroups", "sex,age_group",
            "--decision-thresholds", thresholds,
        ])
    print("[OK] All three synthetic workflows completed successfully")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the external T2D validation package")
    parser.add_argument(
        "--run-synthetic-tests",
        action="store_true",
        help="Also run all three synthetic workflows in a temporary directory.",
    )
    args = parser.parse_args()
    verify_checksums()
    verify_python()
    verify_model()
    if args.run_synthetic_tests:
        synthetic_tests()
    print("\nPACKAGE VERIFICATION PASSED")


if __name__ == "__main__":
    main()
