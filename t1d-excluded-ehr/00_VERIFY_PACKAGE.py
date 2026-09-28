from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import joblib
import pandas as pd


ROOT=Path(__file__).resolve().parent
EXPECTED={
    "compact5": ["depress","depress_age","obesity","obesity_age","rx_any_lipid_statin","rx_1y_lipid_statin","rx_dates1y_lipid_statin","rx_days_lipid_statin","rx_days_lipid_statin_miss","rx_any_mood_antiep","rx_1y_mood_antiep","rx_dates1y_mood_antiep","rx_days_mood_antiep","rx_days_mood_antiep_miss","age_index"],
    "compact10": ["PDD","PDD_age","gestationaldm","gestationaldm_age","hf","hf_age","obesity","obesity_age","sleep","sleep_age","rx_any_mood_antiep","rx_1y_mood_antiep","rx_dates1y_mood_antiep","rx_days_mood_antiep","rx_days_mood_antiep_miss","age_index","age_start","months2index","smoking_proxy_diagnosis"],
}
FILES={"compact5":"compact_5group_5y_bundle.joblib","compact10":"compact_10group_5y_bundle.joblib"}
CONTRACTS={"compact5":"predictors_compact5.csv","compact10":"predictors_compact10.csv"}


def sha256(path:Path)->str:
    digest=hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda:handle.read(1024*1024),b""): digest.update(block)
    return digest.hexdigest()


def verify_checksums()->None:
    for line in (ROOT/"PACKAGE_SHA256SUMS.txt").read_text().splitlines():
        if not line.strip(): continue
        expected,relative=line.split(maxsplit=1)
        if relative.startswith("./"): relative=relative[2:]
        path=ROOT/relative
        if not path.is_file(): raise FileNotFoundError(f"Missing package file: {relative}")
        if sha256(path)!=expected: raise ValueError(f"Checksum mismatch: {relative}")
    print("[OK] All package checksums match")


def verify_python()->None:
    scripts=sorted((ROOT/"src").glob("*.py"))
    for path in scripts: ast.parse(path.read_text(),filename=str(path))
    print(f"[OK] Python syntax parsed for {len(scripts)} scripts")


def verify_models()->None:
    for variant in EXPECTED:
        path=ROOT/"model"/FILES[variant]; bundle=joblib.load(path)
        if not isinstance(bundle,dict) or set(bundle)!={"model","features","calibration"}:
            raise ValueError(f"{variant}: unexpected bundle schema")
        expected=EXPECTED[variant]
        if list(bundle["features"])!=expected: raise ValueError(f"{variant}: bundle feature order mismatch")
        if list(getattr(bundle["model"],"feature_names_in_",[]))!=expected: raise ValueError(f"{variant}: estimator feature order mismatch")
        contract=pd.read_csv(ROOT/"model"/CONTRACTS[variant]).sort_values("order")
        if contract.predictor.tolist()!=expected: raise ValueError(f"{variant}: CSV contract mismatch")
        template=pd.read_csv(ROOT/"definitions"/f"external_input_template_{'5group' if variant == 'compact5' else '10group'}.csv",nrows=0)
        expected_template=["patient_id"]+expected+["dm2","event_years","cohort","sex","age_group"]
        if template.columns.tolist()!=expected_template: raise ValueError(f"{variant}: input-template columns/order mismatch")
        manifest=json.loads((ROOT/"model"/f"{variant}_manifest.json").read_text())
        if manifest.get("calibrated_bundle_sha256")!=sha256(path): raise ValueError(f"{variant}: manifest bundle hash mismatch")
        if manifest.get("predictor_contract_sha256")!=sha256(ROOT/"model"/CONTRACTS[variant]): raise ValueError(f"{variant}: manifest contract hash mismatch")
        calibration=bundle["calibration"]
        if "logistic" not in str(calibration.get("method","")).lower(): raise ValueError(f"{variant}: calibration method missing")
        if "validation" not in str(calibration.get("fit_source","")).lower(): raise ValueError(f"{variant}: calibration source invalid")
        if float(calibration.get("horizon_years",-1))!=5: raise ValueError(f"{variant}: horizon mismatch")
        if float(calibration.get("slope",0))<=0: raise ValueError(f"{variant}: invalid calibration slope")
        if abs(float(manifest["calibration"]["intercept"])-float(calibration["intercept"]))>1e-12: raise ValueError(f"{variant}: calibration intercept mismatch")
        if abs(float(manifest["calibration"]["slope"])-float(calibration["slope"]))>1e-12: raise ValueError(f"{variant}: calibration slope mismatch")
        print(f"[OK] {variant}: {len(expected)} predictors; bundle SHA-256 {sha256(path)}")
    combined_template=pd.read_csv(ROOT/"definitions/external_input_template_both_models.csv",nrows=0)
    combined_expected=["patient_id"]+EXPECTED["compact5"]+[name for name in EXPECTED["compact10"] if name not in EXPECTED["compact5"]]+["dm2","event_years","cohort","sex","age_group"]
    if combined_template.columns.tolist()!=combined_expected: raise ValueError("both-models input-template columns/order mismatch")


def verify_release_text()->None:
    forbidden=("/Users/", "OneDrive-", "patient-level training records")
    for path in list((ROOT/"model").glob("*.json"))+list((ROOT/"examples/configs").glob("*.json")):
        text=path.read_text()
        for token in forbidden[:2]:
            if token in text: raise ValueError(f"Private/internal path found in {path.name}: {token}")
        json.loads(text)
    print("[OK] Release manifests/configurations contain no internal absolute paths")


def run(command:list[str],environment:dict[str,str])->None:
    subprocess.run(command,cwd=ROOT,check=True,env=environment,stdout=subprocess.DEVNULL)


def synthetic_tests()->None:
    script=ROOT/"src/run_external_validation.py"; ex=ROOT/"examples"; defs=ROOT/"definitions"
    environment=dict(os.environ)
    with tempfile.TemporaryDirectory(prefix="t2d_v4_verify_") as temp:
        temp=Path(temp); environment["MPLCONFIGDIR"]=str(temp/"mpl"); environment["XDG_CACHE_HOME"]=str(temp/"cache")
        common=[sys.executable,str(script),"--model-dir",str(ROOT/"model"),"--model-variant","compact5","--model-variant","compact10","--bootstrap","0","--decision-thresholds","0.01,0.03,0.05"]
        run(common+["--final-input",str(ex/"synthetic_site_prepared_final_input.csv"),"--output-dir",str(temp/"final")],environment)
        raw=["--patients",str(ex/"synthetic_raw_patients.csv"),"--diagnoses",str(ex/"synthetic_raw_diagnoses.csv"),"--labs",str(ex/"synthetic_raw_labs.csv"),"--medications",str(ex/"synthetic_raw_medications_atc.csv"),"--medication-lookup",str(defs/"external_atc_medication_lookup.csv"),"--medication-code-system","atc","--phenotype-code-list",str(defs/"phenotype_code_list_REQUIRED.csv")]
        run(common+raw+["--encounters",str(ex/"synthetic_raw_encounters.csv"),"--non-adhd-random-seed","SYNTHETIC-SITE-SEED","--output-dir",str(temp/"longitudinal")],environment)
        raw_no=list(raw); raw_no[1]=str(ex/"synthetic_raw_patients_preassigned_index.csv")
        run(common+raw_no+["--output-dir",str(temp/"no_encounter")],environment)
        for name in ("final","longitudinal","no_encounter"):
            returned=temp/name/"RETURN_TO_COORDINATING_CENTER"/"summary_results"
            if not (returned/"external_metrics.json").is_file(): raise FileNotFoundError(f"Synthetic output missing for {name}")
    print("[OK] Both models completed all three synthetic workflows")


def main()->None:
    parser=argparse.ArgumentParser(); parser.add_argument("--run-synthetic-tests",action="store_true"); args=parser.parse_args()
    verify_checksums(); verify_python(); verify_models(); verify_release_text()
    if args.run_synthetic_tests: synthetic_tests()
    print("\nPACKAGE VERIFICATION PASSED")


if __name__=="__main__": main()
