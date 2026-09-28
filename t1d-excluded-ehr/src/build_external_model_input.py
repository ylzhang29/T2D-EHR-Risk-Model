from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

import numpy as np
import pandas as pd

from external_rf_common import (
    MEDICATION_CLASSES,
    UNION_FEATURE_NAMES,
    read_table,
    save_json,
    validate_predictors,
    write_table,
)


DIAGNOSIS_FEATURES = {
    "depress": "depress", "obesity": "obesity", "pdd": "PDD",
    "gestationaldm": "gestationaldm", "hf": "hf", "sleep": "sleep",
}
ELIGIBILITY_PHENOTYPES = {"t1d", "t2d"}
LANDMARK_PHENOTYPE = "adhd_landmark"
PATIENT_REQUIRED = {
    "patient_id", "birth_date", "ehr_start_date", "ehr_end_date", "cohort",
    "undated_t2d_source_positive",
}


def require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing}")


def parse_date(frame: pd.DataFrame, column: str) -> None:
    frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.normalize()


def binary_value(value: object, label: str) -> int:
    if pd.isna(value):
        raise ValueError(f"Missing {label}")
    text = str(value).strip().lower().replace("_", "-")
    if text in {"1", "1.0", "yes", "true", "adhd"}:
        return 1
    if text in {"0", "0.0", "no", "false", "non-adhd", "no adhd", "control"}:
        return 0
    raise ValueError(f"Unrecognized {label}: {value!r}")


def normalize_code(value: object) -> str:
    return "" if pd.isna(value) else re.sub(r"[^A-Z0-9]", "", str(value).upper())


def normalize_system(value: object) -> str:
    return "" if pd.isna(value) else re.sub(r"[^A-Z0-9]", "", str(value).upper())


def code_matches(code: str, specification: str) -> bool:
    code = normalize_code(code)
    spec_text = str(specification).strip().upper().replace(" ", "")
    match = re.fullmatch(r"([A-Z]?[0-9]{2,3})-([A-Z]?[0-9]{2,3})", spec_text)
    if match:
        start, stop = match.groups(); category = code[:len(start)]
        return len(start) == len(stop) and start <= category <= stop
    spec = normalize_code(spec_text)
    if ".X" in spec_text:
        return re.match("^" + re.escape(spec).replace("X", r"[0-9]"), code) is not None
    return bool(spec) and code.startswith(spec)


def map_diagnoses(diagnoses: pd.DataFrame, code_list_path: Path) -> pd.DataFrame:
    require_columns(diagnoses, {"code_system", "code"}, "raw diagnosis table")
    code_list = pd.read_csv(code_list_path, dtype=str).fillna("")
    require_columns(code_list, {"phenotype", "code_system", "code"}, "phenotype code list")
    diagnoses = diagnoses.copy()
    diagnoses["system_normalized"] = diagnoses.code_system.map(normalize_system)
    diagnoses["code_normalized"] = diagnoses.code.map(normalize_code)
    mapped = []
    allowed = set(DIAGNOSIS_FEATURES) | ELIGIBILITY_PHENOTYPES | {LANDMARK_PHENOTYPE, "smoking_proxy_diagnosis"}
    for row in code_list.itertuples(index=False):
        phenotype = str(row.phenotype).strip().lower()
        if phenotype not in allowed or not str(row.code).strip():
            continue
        candidates = diagnoses[diagnoses.system_normalized == normalize_system(row.code_system)]
        keep = candidates.code_normalized.map(lambda value: code_matches(value, row.code))
        if keep.any():
            part = candidates.loc[keep, ["patient_id", "diagnosis_date"]].copy()
            part["phenotype"] = phenotype
            mapped.append(part)
    if not mapped:
        raise ValueError("No diagnosis rows matched the supplied phenotype code list")
    return pd.concat(mapped, ignore_index=True).drop_duplicates()


def seeded_score(seed: str, patient_id: str, date: pd.Timestamp) -> str:
    return hashlib.sha256(f"{seed}|{patient_id}|{date:%Y-%m-%d}".encode()).hexdigest()


def construct_landmarks(patients: pd.DataFrame, diagnoses: pd.DataFrame,
                        encounters: pd.DataFrame, seed: str, audit: dict) -> pd.DataFrame:
    require_columns(encounters, {"patient_id", "encounter_date"}, "encounter table")
    patients = patients.copy()
    patients["cohort"] = patients.cohort.map(lambda value: binary_value(value, "cohort"))
    encounters = encounters.copy(); encounters["patient_id"] = encounters.patient_id.astype(str)
    parse_date(encounters, "encounter_date")
    encounters = encounters.dropna(subset=["encounter_date"]).drop_duplicates(["patient_id", "encounter_date"])
    encounters = encounters.merge(patients[["patient_id", "ehr_start_date", "ehr_end_date", "cohort"]],
                                    on="patient_id", how="inner", validate="many_to_one")
    encounters = encounters[(encounters.encounter_date >= encounters.ehr_start_date)
                            & (encounters.encounter_date <= encounters.ehr_end_date)]
    adhd_dates = diagnoses[(diagnoses.phenotype == LANDMARK_PHENOTYPE) & diagnoses.diagnosis_date.notna()]
    any_adhd = set(adhd_dates.patient_id)
    invalid_control = (patients.cohort == 0) & patients.patient_id.isin(any_adhd)
    audit["excluded_nonadhd_with_any_adhd_diagnosis"] = int(invalid_control.sum())
    patients = patients.loc[~invalid_control].copy()
    first_adhd = adhd_dates.groupby("patient_id", as_index=False).diagnosis_date.min()
    adhd = patients[patients.cohort == 1].merge(first_adhd, on="patient_id", how="left")
    audit["excluded_adhd_without_dated_diagnosis"] = int(adhd.diagnosis_date.isna().sum())
    adhd = adhd.dropna(subset=["diagnosis_date"]).copy()
    adhd["index_date"] = adhd.diagnosis_date + pd.Timedelta(days=365)
    adhd.drop(columns="diagnosis_date", inplace=True)
    choices = encounters[encounters.cohort == 0][["patient_id", "encounter_date"]].copy()
    choices["score"] = [seeded_score(seed, pid, date) for pid, date in zip(choices.patient_id, choices.encounter_date)]
    selected = choices.sort_values(["patient_id", "score", "encounter_date"]).drop_duplicates("patient_id")
    selected = selected.rename(columns={"encounter_date": "index_date"})[["patient_id", "index_date"]]
    controls = patients[patients.cohort == 0].merge(selected, on="patient_id", how="left")
    audit["excluded_nonadhd_without_encounter"] = int(controls.index_date.isna().sum())
    controls = controls.dropna(subset=["index_date"])
    audit["landmark_mode"] = "ADHD first diagnosis plus 365 days; seeded non-ADHD encounter"
    audit["non_adhd_random_seed"] = seed
    return pd.concat([adhd, controls], ignore_index=True)


def diabetic_range_lab_ids(labs: pd.DataFrame, patients: pd.DataFrame, audit: dict) -> set[str]:
    require_columns(labs, {"patient_id", "loinc_code", "result_date", "result_value", "result_unit", "fasting_verified"}, "laboratory table")
    audit["laboratory_source_provided"] = True
    audit["laboratory_rows_input"] = int(len(labs))
    labs = labs.copy(); labs["patient_id"] = labs.patient_id.astype(str)
    parse_date(labs, "result_date")
    labs["loinc"] = labs.loinc_code.astype(str).str.strip()
    labs["value"] = pd.to_numeric(labs.result_value, errors="coerce")
    labs["unit"] = labs.result_unit.astype(str).str.strip().str.lower().str.replace(" ", "", regex=False)
    labs["fasting"] = labs.fasting_verified.map(lambda value: binary_value(value, "fasting_verified"))
    labs = labs.merge(patients[["patient_id", "index_date"]], on="patient_id", how="inner")
    labs = labs[labs.result_date.notna() & labs.value.notna() & (labs.result_date <= labs.index_date)]
    audit["laboratory_rows_valid_preindex"] = int(len(labs))
    hba_percent = labs.loinc.isin(["4548-4", "17856-6"]) & labs.unit.isin(["%", "percent"]) & (labs.value >= 6.5)
    hba_ifcc = (labs.loinc == "59261-8") & labs.unit.isin(["mmol/mol", "mmolmol"]) & (labs.value >= 48)
    fasting_mg = (labs.loinc == "1558-6") & (labs.fasting == 1) & labs.unit.isin(["mg/dl", "mgdl"]) & (labs.value >= 126)
    fasting_mmol = (labs.loinc == "1558-6") & (labs.fasting == 1) & labs.unit.isin(["mmol/l", "mmoll"]) & (labs.value >= 7.0)
    abnormal = labs[hba_percent | hba_ifcc | fasting_mg | fasting_mmol]
    audit["diabetic_range_laboratory_rows"] = int(len(abnormal))
    counts = abnormal.groupby("patient_id").result_date.nunique()
    ids = set(counts[counts >= 2].index)
    audit["patients_excluded_two_or_more_diabetic_range_lab_dates"] = int(len(ids))
    audit["eligible_lab_rule"] = "at least 2 distinct on/before-index diabetic-range dates across HbA1c or verified fasting glucose"
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the T1D-excluded EHR external-validation table")
    parser.add_argument("--patients", type=Path, required=True)
    parser.add_argument("--encounters", type=Path)
    parser.add_argument("--non-adhd-random-seed")
    parser.add_argument("--diagnoses", type=Path, required=True)
    parser.add_argument("--labs", type=Path)
    parser.add_argument("--glycemic-lab-baseline-exclusion-unavailable", action="store_true",
                        help="Explicitly allow no laboratory source for the baseline glycemic exclusion rule.")
    parser.add_argument("--medications", type=Path, required=True)
    parser.add_argument("--medication-lookup", type=Path, required=True)
    parser.add_argument("--medication-code-system", choices=("auto", "atc", "rxnorm"), default="auto")
    parser.add_argument("--phenotype-code-list", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-json", type=Path)
    args = parser.parse_args()

    if args.labs is None and not args.glycemic_lab_baseline_exclusion_unavailable:
        raise ValueError("--labs is required unless --glycemic-lab-baseline-exclusion-unavailable is specified")
    if args.labs is not None and args.glycemic_lab_baseline_exclusion_unavailable:
        raise ValueError("Provide --labs for full-protocol eligibility, or omit it and explicitly declare the unavailable-lab deviation")
    patients = read_table(args.patients); diagnoses = read_table(args.diagnoses)
    labs = read_table(args.labs) if args.labs is not None else None; medications = read_table(args.medications)
    lookup = pd.read_csv(args.medication_lookup, dtype=str).fillna("")
    require_columns(patients, PATIENT_REQUIRED, "patient table")
    require_columns(diagnoses, {"patient_id", "diagnosis_date"}, "diagnosis table")
    require_columns(medications, {"patient_id", "start_date"}, "medication table")
    if patients.patient_id.isna().any() or patients.patient_id.astype(str).duplicated().any():
        raise ValueError("patient_id must be complete and unique in the patient table")
    for frame in (patients, diagnoses, medications): frame["patient_id"] = frame.patient_id.astype(str)
    for column in ("birth_date", "ehr_start_date", "ehr_end_date"):
        parse_date(patients, column)
    if "death_date" not in patients: patients["death_date"] = pd.NaT
    else: parse_date(patients, "death_date")
    if "index_date" in patients: parse_date(patients, "index_date")
    parse_date(diagnoses, "diagnosis_date"); parse_date(medications, "start_date")
    invalid_diagnosis_dates = int(diagnoses.diagnosis_date.isna().sum())
    if "phenotype" not in diagnoses:
        if args.phenotype_code_list is None:
            raise ValueError("Raw diagnosis codes require --phenotype-code-list")
        diagnoses = map_diagnoses(diagnoses, args.phenotype_code_list)
    diagnoses["phenotype"] = diagnoses.phenotype.astype(str).str.strip().str.lower()
    audit = {"package_version": "4.0", "patients_input": int(len(patients)),
             "diagnosis_rows_input": int(len(diagnoses)), "diagnosis_rows_invalid_date": invalid_diagnosis_dates,
             "medication_evidence_used_for_eligibility_or_outcome": False,
             "glycemic_lab_baseline_exclusion": "unavailable" if args.glycemic_lab_baseline_exclusion_unavailable else "applied"}
    if args.encounters is not None:
        if not args.non_adhd_random_seed:
            raise ValueError("--encounters requires --non-adhd-random-seed")
        patients = construct_landmarks(patients, diagnoses, read_table(args.encounters), str(args.non_adhd_random_seed), audit)
    else:
        require_columns(patients, {"index_date"}, "patient table without encounters")
        if args.non_adhd_random_seed:
            raise ValueError("--non-adhd-random-seed is used only with encounters")
        patients["cohort"] = patients.cohort.map(lambda value: binary_value(value, "cohort"))
        adhd_dates = diagnoses[(diagnoses.phenotype == LANDMARK_PHENOTYPE) & diagnoses.diagnosis_date.notna()]
        any_adhd_ids = set(adhd_dates.patient_id)
        invalid_controls = (patients.cohort == 0) & patients.patient_id.isin(any_adhd_ids)
        audit["excluded_nonadhd_with_any_adhd_diagnosis"] = int(invalid_controls.sum())
        patients = patients.loc[~invalid_controls].copy()
        first_adhd = adhd_dates.groupby("patient_id").diagnosis_date.min()
        expected = patients.patient_id.map(first_adhd) + pd.Timedelta(days=365)
        invalid_adhd = (patients.cohort == 1) & (expected.isna() | (patients.index_date != expected))
        audit["excluded_adhd_with_invalid_preassigned_index"] = int(invalid_adhd.sum())
        patients = patients.loc[~invalid_adhd].copy()
        audit["landmark_mode"] = "site-preassigned index_date"
    missing = patients[["birth_date", "ehr_start_date", "ehr_end_date", "index_date"]].isna().any(axis=1)
    audit["excluded_missing_required_dates"] = int(missing.sum()); patients = patients.loc[~missing].copy()
    chronology = (patients.birth_date > patients.ehr_start_date) | (patients.ehr_start_date > patients.index_date)
    if chronology.any(): raise ValueError(f"birth_date <= ehr_start_date <= index_date required; bad rows={int(chronology.sum())}")
    patients["censor_date"] = patients.ehr_end_date
    death_first = patients.death_date.notna() & (patients.death_date < patients.censor_date)
    patients.loc[death_first, "censor_date"] = patients.loc[death_first, "death_date"]
    no_followup = patients.censor_date <= patients.index_date
    audit["excluded_no_post_index_followup"] = int(no_followup.sum()); patients = patients.loc[~no_followup].copy()

    undated_flag = patients.undated_t2d_source_positive.map(lambda value: binary_value(value, "undated_t2d_source_positive")) == 1
    undated_ids = set(patients.loc[undated_flag, "patient_id"])
    undated_ids |= set(diagnoses.loc[(diagnoses.phenotype == "t2d") & diagnoses.diagnosis_date.isna(), "patient_id"])
    audit["excluded_undated_source_positive_t2d"] = int(patients.patient_id.isin(undated_ids).sum())
    patients = patients[~patients.patient_id.isin(undated_ids)].copy()
    dated = diagnoses[diagnoses.diagnosis_date.notna()].merge(patients[["patient_id", "index_date"]], on="patient_id", how="inner")
    pre_t2d = set(dated.loc[(dated.phenotype == "t2d") & (dated.diagnosis_date <= dated.index_date), "patient_id"])
    pre_t1d = set(dated.loc[(dated.phenotype == "t1d") & (dated.diagnosis_date <= dated.index_date), "patient_id"])
    audit["excluded_t2d_on_or_before_index"] = int(patients.patient_id.isin(pre_t2d).sum())
    patients = patients[~patients.patient_id.isin(pre_t2d)].copy()
    audit["excluded_t1d_on_or_before_index"] = int(patients.patient_id.isin(pre_t1d).sum())
    patients = patients[~patients.patient_id.isin(pre_t1d)].copy()
    if labs is None:
        audit["laboratory_source_provided"] = False
        audit["laboratory_rows_input"] = None
        audit["laboratory_rows_valid_preindex"] = None
        audit["diabetic_range_laboratory_rows"] = None
        audit["patients_excluded_two_or_more_diabetic_range_lab_dates"] = None
        audit["eligible_lab_rule"] = "not applied: source laboratory data unavailable; explicit protocol deviation"
        audit["analysis_label"] = "T1D-excluded model validation with glycemic-laboratory baseline exclusion unavailable"
    else:
        lab_excluded = diabetic_range_lab_ids(labs, patients, audit)
        patients = patients[~patients.patient_id.isin(lab_excluded)].copy()

    output = patients.copy()
    output["age_index"] = (output.index_date - output.birth_date).dt.days / 365.25
    output["age_start"] = (output.ehr_start_date - output.birth_date).dt.days / 365.25
    output["months2index"] = (output.index_date - output.ehr_start_date).dt.days / 30.4375
    prior = diagnoses[diagnoses.diagnosis_date.notna()].merge(output[["patient_id", "index_date", "birth_date"]], on="patient_id", how="inner")
    prior = prior[prior.diagnosis_date <= prior.index_date]
    first = prior.groupby(["patient_id", "phenotype"], as_index=False).diagnosis_date.min()
    for phenotype, external_name in DIAGNOSIS_FEATURES.items():
        selected = first[first.phenotype == phenotype][["patient_id", "diagnosis_date"]].rename(columns={"diagnosis_date": "feature_date"})
        output = output.merge(selected, on="patient_id", how="left")
        output[external_name] = output.feature_date.notna().astype(np.uint8)
        output[f"{external_name}_age"] = np.where(output[external_name] == 1,
            (output.feature_date - output.birth_date).dt.days / 365.25, -1.0)
        output.drop(columns="feature_date", inplace=True)
    smoking_ids = set(prior.loc[prior.phenotype == "smoking_proxy_diagnosis", "patient_id"])
    output["smoking_proxy_diagnosis"] = output.patient_id.isin(smoking_ids).astype(np.uint8)

    if args.medication_code_system == "auto":
        available = [c for c in ("atc_code", "rxcui") if c in medications]
        if len(available) != 1: raise ValueError("Medication table must contain exactly one of atc_code or rxcui in auto mode")
        code_column = available[0]
    else: code_column = "atc_code" if args.medication_code_system == "atc" else "rxcui"
    require_columns(medications, {code_column}, "medication table")
    require_columns(lookup, {code_column, "med_feature", "primary_include"}, "medication lookup")
    if code_column == "atc_code":
        medications[code_column] = medications[code_column].map(normalize_code)
        lookup[code_column] = lookup[code_column].map(normalize_code)
        invalid = medications[code_column].ne("") & ~medications[code_column].str.fullmatch(r"[A-Z][0-9]{2}[A-Z]{2}[0-9]{2}")
        if invalid.any(): raise ValueError("ATC input must contain exact fifth-level ingredient codes")
    else:
        medications[code_column] = medications[code_column].astype(str).str.strip()
        lookup[code_column] = lookup[code_column].astype(str).str.strip()
    locked = lookup[lookup.med_feature.isin(MEDICATION_CLASSES) & lookup.primary_include.astype(str).eq("1")][[code_column, "med_feature"]].drop_duplicates()
    meds = medications.dropna(subset=["start_date"]).merge(locked, on=code_column, how="inner")
    meds = meds.merge(output[["patient_id", "index_date"]], on="patient_id", how="inner")
    meds = meds[meds.start_date < meds.index_date].copy()
    meds["in_1y"] = meds.start_date >= meds.index_date - pd.Timedelta(days=365)
    for med in MEDICATION_CLASSES:
        part = meds[meds.med_feature == med]
        aggregate = part.groupby("patient_id").agg(most_recent=("start_date", "max"), any_1y=("in_1y", "max"))
        dates = part[part.in_1y].groupby("patient_id").start_date.nunique().rename("dates_1y")
        aggregate = aggregate.join(dates).reset_index()
        output = output.merge(aggregate, on="patient_id", how="left")
        present = output.most_recent.notna()
        output[f"rx_any_{med}"] = present.astype(np.uint8)
        output[f"rx_1y_{med}"] = output.any_1y.fillna(False).astype(np.uint8)
        output[f"rx_dates1y_{med}"] = output.dates_1y.fillna(0).astype(int)
        output[f"rx_days_{med}"] = np.where(present, (output.index_date - output.most_recent).dt.days, -100)
        output[f"rx_days_{med}_miss"] = (~present).astype(np.uint8)
        output.drop(columns=["most_recent", "any_1y", "dates_1y"], inplace=True)

    post = diagnoses[(diagnoses.phenotype == "t2d") & diagnoses.diagnosis_date.notna()].merge(
        output[["patient_id", "index_date", "censor_date"]], on="patient_id", how="inner")
    post = post[(post.diagnosis_date > post.index_date) & (post.diagnosis_date <= post.censor_date)]
    event_date = post.groupby("patient_id", as_index=False).diagnosis_date.min().rename(columns={"diagnosis_date": "first_post_t2d_date"})
    output = output.merge(event_date, on="patient_id", how="left")
    output["dm2"] = output.first_post_t2d_date.notna().astype(np.uint8)
    end = output.first_post_t2d_date.fillna(output.censor_date)
    output["event_years"] = (end - output.index_date).dt.days / 365.25
    output = output[np.isfinite(output.event_years) & (output.event_years > 0)].copy()
    validate_predictors(output, ["compact5", "compact10"], strict=True)
    output["age_group"] = pd.cut(output.age_index, [-np.inf, 17, 34, 49, 64, np.inf], labels=["<18", "18-34", "35-49", "50-64", ">=65"]).astype(str)
    optional = [name for name in ("cohort", "sex") if name in output]
    output = output[["patient_id"] + UNION_FEATURE_NAMES + ["dm2", "event_years"] + optional + ["age_group"]]
    audit.update({"patients_output": int(len(output)), "post_index_t2d_events": int(output.dm2.sum()),
                  "predictor_columns_union": UNION_FEATURE_NAMES,
                  "primary_outcome": "first recorded post-landmark T2D diagnosis"})
    write_table(output, args.output)
    save_json(audit, args.audit_json or args.output.with_name(args.output.stem + "_audit.json"))
    print(f"Built {len(output):,} eligible external-validation rows")


if __name__ == "__main__":
    main()
