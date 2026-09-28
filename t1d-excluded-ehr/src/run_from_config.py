from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser=argparse.ArgumentParser(description="Run T1D-excluded EHR external validation from one JSON configuration")
    parser.add_argument("--config",type=Path,required=True); args=parser.parse_args()
    config_path=args.config.resolve(); config=json.loads(config_path.read_text()); base=config_path.parent
    def resolved(name:str,required:bool=True):
        value=config.get(name)
        if value in (None,""):
            if required: raise ValueError(f"Configuration is missing: {name}")
            return None
        path=Path(value); return path if path.is_absolute() else (base/path).resolve()
    variants=config.get("model_variants",["compact5","compact10"])
    if not isinstance(variants,list) or not variants: raise ValueError("model_variants must be a nonempty JSON list")
    command=[sys.executable,str(Path(__file__).with_name("run_external_validation.py")),"--model-dir",str(resolved("model_dir")),
             "--output-dir",str(resolved("output_dir")),"--bootstrap",str(int(config.get("bootstrap",500))),
             "--bootstrap-seed",str(int(config.get("bootstrap_seed",20260322))),"--subgroups",str(config.get("subgroups","sex,age_group,cohort")),
             "--decision-thresholds",str(config.get("decision_thresholds",""))]
    for variant in variants: command += ["--model-variant",variant]
    if config.get("fit_local_recalibration_secondary",False): command.append("--fit-local-recalibration-secondary")
    glycemic_lab_available=config.get("glycemic_lab_available",True)
    if not isinstance(glycemic_lab_available,bool):
        raise ValueError("glycemic_lab_available must be true or false")
    final=resolved("final_input",False)
    if final: command += ["--final-input",str(final)]
    else:
        for name in ("patients","diagnoses","medications","medication_lookup"):
            command += ["--"+name.replace("_","-"),str(resolved(name))]
        labs=resolved("labs",False)
        if glycemic_lab_available and labs: command += ["--labs",str(labs)]
        command += ["--medication-code-system",str(config.get("medication_code_system","auto"))]
        for name in ("encounters","phenotype_code_list"):
            path=resolved(name,False)
            if path: command += ["--"+name.replace("_","-"),str(path)]
        if config.get("non_adhd_random_seed") not in (None,""):
            command += ["--non-adhd-random-seed",str(config["non_adhd_random_seed"])]
    if not glycemic_lab_available:
        command.append("--glycemic-lab-baseline-exclusion-unavailable")
    subprocess.run(command,check=True)


if __name__=="__main__": main()
