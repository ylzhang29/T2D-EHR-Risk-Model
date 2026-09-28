from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import os
import platform
import subprocess
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from external_rf_common import FEATURE_NAMES, MODEL_FILES, MODEL_VARIANTS, read_table, save_json, validate_predictors


def sha256(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda:handle.read(1024*1024),b""): digest.update(block)
    return digest.hexdigest()


def run(command: list[str], environment: dict[str,str]) -> None:
    print("\nRunning:"," ".join(command),flush=True); subprocess.run(command,check=True,env=environment)


def main() -> None:
    parser=argparse.ArgumentParser(description="Build, score, and evaluate the frozen T1D-excluded EHR models")
    parser.add_argument("--model-dir",type=Path,required=True)
    parser.add_argument("--model-variant",action="append",choices=MODEL_VARIANTS,required=True,
                        help="Repeat to score both models in one paired run.")
    parser.add_argument("--final-input",type=Path)
    parser.add_argument("--patients",type=Path); parser.add_argument("--encounters",type=Path)
    parser.add_argument("--non-adhd-random-seed"); parser.add_argument("--diagnoses",type=Path)
    parser.add_argument("--labs",type=Path); parser.add_argument("--medications",type=Path)
    parser.add_argument("--medication-lookup",type=Path); parser.add_argument("--medication-code-system",choices=("auto","atc","rxnorm"),default="auto")
    parser.add_argument("--phenotype-code-list",type=Path)
    parser.add_argument("--output-dir",type=Path,required=True); parser.add_argument("--bootstrap",type=int,default=500)
    parser.add_argument("--bootstrap-seed",type=int,default=20260322); parser.add_argument("--subgroups",default="sex,age_group,cohort")
    parser.add_argument("--decision-thresholds",default="")
    parser.add_argument("--fit-local-recalibration-secondary",action="store_true")
    args=parser.parse_args(); variants=list(dict.fromkeys(args.model_variant))
    raw_names=("patients","diagnoses","labs","medications","medication_lookup")
    if args.final_input is None:
        missing=[name for name in raw_names if getattr(args,name) is None]
        if missing: raise ValueError("Raw-input mode is missing: "+", ".join(missing))
    elif any(getattr(args,name) is not None for name in raw_names+("encounters","phenotype_code_list")):
        raise ValueError("--final-input cannot be combined with raw longitudinal inputs")
    script_dir=Path(__file__).resolve().parent; args.output_dir.mkdir(parents=True,exist_ok=True)
    local=args.output_dir/"LOCAL_ONLY_DO_NOT_RETURN"; returned=args.output_dir/"RETURN_TO_COORDINATING_CENTER"; results=returned/"summary_results"
    local.mkdir(exist_ok=True); returned.mkdir(exist_ok=True); results.mkdir(exist_ok=True)
    constructed=args.final_input if args.final_input else local/"external_model_input.parquet"
    scored=local/"external_patient_scores.parquet"; audit_path=returned/"external_model_input_audit.json"
    environment=dict(os.environ); environment["MPLCONFIGDIR"]=str(local/".matplotlib"); (local/".matplotlib").mkdir(exist_ok=True)
    inputs={"site_prepared_final_input":args.final_input} if args.final_input else {name:getattr(args,name) for name in raw_names}
    if args.encounters: inputs["encounters"]=args.encounters
    if args.phenotype_code_list: inputs["phenotype_code_list"]=args.phenotype_code_list
    model_info={}
    for variant in variants:
        path=args.model_dir/MODEL_FILES[variant]; bundle=joblib.load(path)
        model_info[variant]={"filename":path.name,"sha256":sha256(path),"features":bundle.get("features"),"calibration":bundle.get("calibration")}
    save_json({"package_version":"4.0","analysis":"external validation of first recorded post-landmark T2D diagnosis",
               "not_biological_onset_or_clinical_deployment":True,"input_mode":"site_prepared_final_input" if args.final_input else "raw_longitudinal_inputs",
               "models":model_info,"input_files":{name:{"filename":path.name,"sha256":sha256(path)} for name,path in inputs.items() if path},
               "natural_frequency_required":True,"bootstrap_replicates":args.bootstrap,"bootstrap_seed":args.bootstrap_seed,
               "decision_thresholds_prespecified":args.decision_thresholds,"local_recalibration_secondary_requested":args.fit_local_recalibration_secondary,
               "patient_level_data_and_predictions_remain_local":True,
               "software":{"python":platform.python_version(),"numpy":np.__version__,"pandas":pd.__version__,
                           "pyarrow":importlib.metadata.version("pyarrow"),"scikit_learn":importlib.metadata.version("scikit-learn"),
                           "joblib":joblib.__version__,"matplotlib":importlib.metadata.version("matplotlib")}},returned/"run_manifest.json")
    if args.final_input:
        frame=read_table(args.final_input); validate_predictors(frame,variants,strict=True)
        required={"patient_id","dm2","event_years"}; missing=sorted(required-set(frame.columns))
        if missing: raise ValueError(f"Final input is missing: {missing}")
        if frame.patient_id.isna().any() or frame.patient_id.astype(str).duplicated().any(): raise ValueError("patient_id must be complete and unique")
        if not frame.dm2.isin([0,1,False,True]).all(): raise ValueError("dm2 must contain only 0/1")
        if frame.event_years.isna().any() or (frame.event_years<=0).any(): raise ValueError("event_years must be complete and >0")
        save_json({"input_mode":"site_prepared_final_input","site_attestation_required":True,"patients":len(frame),"events":int(frame.dm2.sum()),
                   "validated_model_contracts":{v:FEATURE_NAMES[v] for v in variants},
                   "construction_not_reaudited":"Landmark, eligibility, predictors, outcome, and censoring must be attested by the site."},audit_path)
    else:
        command=[sys.executable,str(script_dir/"build_external_model_input.py"),"--patients",str(args.patients),"--diagnoses",str(args.diagnoses),
                 "--labs",str(args.labs),"--medications",str(args.medications),"--medication-lookup",str(args.medication_lookup),
                 "--medication-code-system",args.medication_code_system,"--output",str(constructed),"--audit-json",str(audit_path)]
        if args.encounters:
            if not args.non_adhd_random_seed: raise ValueError("--encounters requires --non-adhd-random-seed")
            command += ["--encounters",str(args.encounters),"--non-adhd-random-seed",str(args.non_adhd_random_seed)]
        if args.phenotype_code_list: command += ["--phenotype-code-list",str(args.phenotype_code_list)]
        run(command,environment)
    variants_args=sum((["--model-variant",v] for v in variants),[])
    run([sys.executable,str(script_dir/"score_saved_model.py"),"--input",str(constructed),"--output",str(scored),"--model-dir",str(args.model_dir)]+variants_args,environment)
    command=[sys.executable,str(script_dir/"evaluate_external_validation.py"),"--input",str(scored),"--output-dir",str(results),
             "--bootstrap",str(args.bootstrap),"--seed",str(args.bootstrap_seed),"--subgroups",args.subgroups,
             "--decision-thresholds",args.decision_thresholds]+variants_args
    if args.fit_local_recalibration_secondary: command.append("--fit-local-recalibration-secondary")
    run(command,environment)
    print("\nExternal validation completed successfully.")
    print(f"LOCAL ONLY — do not return: {local}"); print(f"SAFE RETURN DIRECTORY: {returned}")


if __name__=="__main__": main()
