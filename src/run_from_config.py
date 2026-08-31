from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the external T2D validation from one site configuration file"
    )
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()

    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    base = config_path.parent

    def resolved(name: str, required: bool = True) -> Path | None:
        value = config.get(name)
        if value in (None, ""):
            if required:
                raise ValueError(f"Configuration is missing: {name}")
            return None
        path = Path(value)
        return path if path.is_absolute() else (base / path).resolve()

    script = Path(__file__).resolve().with_name("run_external_validation.py")
    command = [
        sys.executable,
        str(script),
        "--model", str(resolved("model")),
        "--output-dir", str(resolved("output_dir")),
        "--bootstrap", str(int(config.get("bootstrap", 500))),
        "--subgroups", str(config.get("subgroups", "sex,age_group")),
        "--decision-thresholds", str(config.get("decision_thresholds", "")),
    ]
    final_input = resolved("final_input", required=False)
    if final_input is not None:
        raw_keys = ("patients", "encounters", "diagnoses", "medications", "medication_lookup")
        conflicts = [name for name in raw_keys if config.get(name) not in (None, "")]
        if conflicts:
            raise ValueError(
                "Configuration final_input cannot be combined with: "
                + ", ".join(conflicts)
            )
        command.extend(["--final-input", str(final_input)])
        print("Running site-prepared final-input mode")
        print("Site attestation is required; raw construction is not re-audited.")
        print("Running site configuration:", config_path)
        subprocess.run(command, check=True)
        return

    command.extend([
        "--patients", str(resolved("patients")),
        "--diagnoses", str(resolved("diagnoses")),
        "--medications", str(resolved("medications")),
        "--medication-lookup", str(resolved("medication_lookup")),
        "--medication-code-system", str(config.get("medication_code_system", "auto")),
    ])
    phenotype = resolved("phenotype_code_list", required=False)
    if phenotype is not None:
        command.extend(["--phenotype-code-list", str(phenotype)])
    encounters = resolved("encounters", required=False)
    if encounters is not None:
        seed = config.get("non_adhd_random_seed")
        if seed in (None, ""):
            raise ValueError(
                "Configuration with encounters requires non_adhd_random_seed"
            )
        command.extend([
            "--encounters", str(encounters),
            "--non-adhd-random-seed", str(seed),
        ])
    elif config.get("non_adhd_random_seed") not in (None, ""):
        raise ValueError("non_adhd_random_seed is used only when encounters is supplied")

    print("Running site configuration:", config_path)
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
