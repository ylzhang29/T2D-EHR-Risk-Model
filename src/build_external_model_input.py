from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

import numpy as np
import pandas as pd

from external_rf_common import (
    FEATURE_NAMES,
    MEDICATION_CLASSES,
    read_table,
    save_json,
    validate_predictors,
    write_table,
)


PATIENT_REQUIRED = {
    "patient_id",
    "birth_date",
    "ehr_start_date",
    "ehr_end_date",
    "marital_status",
}
DIAGNOSIS_BASE_REQUIRED = {"patient_id", "diagnosis_date"}
MEDICATION_BASE_REQUIRED = {"patient_id", "start_date"}
LOCKED_DIAGNOSES = ("cvd_any", "hypert", "dm1", "obesity")
LANDMARK_PHENOTYPE = "adhd_landmark"


def require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing}")


def parse_date(frame: pd.DataFrame, column: str) -> None:
    frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.normalize()


def cohort_binary(value: object) -> int | None:
    """Map documented ADHD/non-ADHD representations to 1/0."""
    if pd.isna(value):
        return None
    text = str(value).strip().lower().replace("_", "-")
    if text in {"1", "1.0", "adhd", "yes", "true"}:
        return 1
    if text in {"0", "0.0", "non-adhd", "no adhd", "control", "no", "false"}:
        return 0
    return None


def seeded_score(seed: str, patient_id: str, encounter_date: pd.Timestamp) -> str:
    """Stable pseudo-random score, independent of input row order."""
    token = f"{seed}|{patient_id}|{encounter_date:%Y-%m-%d}".encode("utf-8")
    return hashlib.sha256(token).hexdigest()


def construct_prediction_landmarks(
    patients: pd.DataFrame,
    diagnoses: pd.DataFrame,
    encounters: pd.DataFrame,
    seed: str,
    audit: dict,
) -> pd.DataFrame:
    require_columns(patients, {"cohort"}, "patient table in landmark-construction mode")
    require_columns(encounters, {"patient_id", "encounter_date"}, "encounter table")
    mapped_cohort = patients.cohort.map(cohort_binary)
    if mapped_cohort.isna().any():
        examples = patients.loc[mapped_cohort.isna(), "cohort"].astype(str).unique()[:10]
        raise ValueError(f"cohort must identify ADHD/non-ADHD; unrecognized examples: {examples}")
    patients = patients.copy()
    patients["cohort"] = mapped_cohort.astype(np.uint8)

    encounters = encounters.copy()
    encounters["patient_id"] = encounters.patient_id.astype(str)
    parse_date(encounters, "encounter_date")
    audit["encounter_rows_input"] = int(len(encounters))
    audit["encounter_rows_missing_or_invalid_date"] = int(encounters.encounter_date.isna().sum())
    encounters = encounters[encounters.encounter_date.notna()].copy()
    encounters = encounters.merge(
        patients[["patient_id", "ehr_start_date", "ehr_end_date", "cohort"]],
        on="patient_id",
        how="inner",
        validate="many_to_one",
    )
    encounters = encounters[
        (encounters.encounter_date >= encounters.ehr_start_date)
        & (encounters.encounter_date <= encounters.ehr_end_date)
    ].copy()
    # The protocol selects a random observable timing. Duplicate rows on the
    # same patient/date do not change that timing and are removed.
    encounters = encounters.drop_duplicates(["patient_id", "encounter_date"])
    audit["eligible_unique_encounter_dates"] = int(len(encounters))

    adhd_dates = diagnoses[
        (diagnoses.phenotype == LANDMARK_PHENOTYPE)
        & diagnoses.diagnosis_date.notna()
    ].copy()
    first_adhd = (
        adhd_dates.groupby("patient_id", as_index=False).diagnosis_date.min()
        .rename(columns={"diagnosis_date": "first_adhd_date"})
    )
    any_adhd_ids = set(adhd_dates.patient_id)
    invalid_controls = (patients.cohort == 0) & patients.patient_id.isin(any_adhd_ids)
    audit["non_adhd_patients_dropped_with_any_adhd_diagnosis"] = int(invalid_controls.sum())
    patients = patients.loc[~invalid_controls].copy()

    adhd = patients[patients.cohort == 1].merge(
        first_adhd, on="patient_id", how="left", validate="one_to_one"
    )
    missing_adhd = adhd.first_adhd_date.isna()
    audit["adhd_patients_dropped_without_qualifying_adhd_date"] = int(missing_adhd.sum())
    adhd = adhd.loc[~missing_adhd].copy()
    adhd["index_date"] = adhd.first_adhd_date + pd.to_timedelta(365, unit="day")
    adhd.drop(columns="first_adhd_date", inplace=True)

    controls = patients[patients.cohort == 0].copy()
    eligible_control_dates = encounters[encounters.cohort == 0][
        ["patient_id", "encounter_date"]
    ].copy()
    eligible_control_dates["seeded_score"] = [
        seeded_score(seed, patient_id, encounter_date)
        for patient_id, encounter_date in zip(
            eligible_control_dates.patient_id,
            eligible_control_dates.encounter_date,
        )
    ]
    selected = (
        eligible_control_dates.sort_values(
            ["patient_id", "seeded_score", "encounter_date"]
        )
        .drop_duplicates("patient_id")
        .rename(columns={"encounter_date": "index_date"})
        [["patient_id", "index_date"]]
    )
    controls = controls.merge(selected, on="patient_id", how="left", validate="one_to_one")
    missing_control = controls.index_date.isna()
    audit["non_adhd_patients_dropped_without_eligible_encounter"] = int(missing_control.sum())
    controls = controls.loc[~missing_control].copy()

    audit["landmark_mode"] = "constructed_from_first_adhd_diagnosis_and_seeded_control_encounter"
    audit["non_adhd_random_seed"] = str(seed)
    audit["adhd_landmarks_constructed"] = int(len(adhd))
    audit["non_adhd_landmarks_constructed"] = int(len(controls))
    return pd.concat([adhd, controls], ignore_index=True)


def normalize_code(value: object) -> str:
    if pd.isna(value):
        return ""
    # Diagnosis sources commonly alternate between dotted and dotless forms
    # (for example E11.9 and E119). Match on a punctuation-free form.
    return re.sub(r"[^A-Z0-9]", "", str(value).strip().upper())


def normalize_code_system(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).strip().upper())


def normalize_atc(value: object) -> str:
    """Normalize a fifth-level ATC code for exact lookup matching."""
    if pd.isna(value):
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(value).strip().upper())


def medication_code_contract(
    medications: pd.DataFrame,
    lookup: pd.DataFrame,
    requested_system: str,
) -> tuple[str, str]:
    available = [name for name in ("atc_code", "rxcui") if name in medications]
    if requested_system == "auto":
        if len(available) != 1:
            raise ValueError(
                "With --medication-code-system auto, the medication table must "
                "contain exactly one of atc_code or rxcui"
            )
        code_system = "atc" if available[0] == "atc_code" else "rxnorm"
    else:
        code_system = requested_system
    code_column = "atc_code" if code_system == "atc" else "rxcui"
    require_columns(medications, {code_column}, "medication table")
    require_columns(
        lookup,
        {code_column, "med_feature", "primary_include"},
        f"{code_system} medication lookup",
    )
    return code_system, code_column


def code_matches(code: str, specification: str) -> bool:
    code = normalize_code(code)
    specification_text = str(specification).strip().upper().replace(" ", "")
    range_match = re.fullmatch(
        r"([A-Z]?[0-9]{2,3})-([A-Z]?[0-9]{2,3})", specification_text
    )
    if range_match:
        start, stop = range_match.groups()
        if len(start) != len(stop):
            return False
        category = code[:len(start)]
        return len(category) == len(start) and start <= category <= stop
    specification_normalized = normalize_code(specification_text)
    # The supplied legacy ICD-9 definitions use forms such as 250.X1,
    # where X means any single digit in that position.
    if ".X" in specification_text:
        wildcard_pattern = "^" + re.escape(specification_normalized).replace(
            "X", r"[0-9]"
        )
        return re.match(wildcard_pattern, code) is not None
    return bool(specification_normalized) and code.startswith(specification_normalized)


def map_diagnosis_codes(diagnoses: pd.DataFrame, code_list_path: Path) -> pd.DataFrame:
    require_columns(diagnoses, {"code_system", "code"}, "raw diagnosis table")
    code_list = pd.read_csv(code_list_path, dtype=str).fillna("")
    require_columns(code_list, {"phenotype", "code_system", "code"}, "phenotype code list")
    code_list["phenotype"] = code_list.phenotype.str.strip().str.lower()
    code_list = code_list[
        code_list.phenotype.isin(list(LOCKED_DIAGNOSES) + ["dm2", LANDMARK_PHENOTYPE])
        & code_list.code.str.strip().ne("")
    ].copy()
    missing_phenotypes = sorted(
        set(LOCKED_DIAGNOSES + ("dm2",)) - set(code_list.phenotype)
    )
    if missing_phenotypes:
        raise ValueError(
            "Phenotype code list is incomplete. Add codes for: "
            + ", ".join(missing_phenotypes)
        )
    diagnoses = diagnoses.copy()
    diagnoses["code_system_normalized"] = diagnoses.code_system.map(normalize_code_system)
    diagnoses["code_normalized"] = diagnoses.code.map(normalize_code)
    mapped = []
    for row in code_list.itertuples(index=False):
        system = normalize_code_system(row.code_system)
        candidates = diagnoses[diagnoses.code_system_normalized == system]
        keep = candidates.code_normalized.map(lambda value: code_matches(value, row.code))
        if keep.any():
            part = candidates.loc[keep, ["patient_id", "diagnosis_date"]].copy()
            part["phenotype"] = row.phenotype
            mapped.append(part)
    if not mapped:
        raise ValueError("No diagnosis rows matched the supplied phenotype code list")
    return pd.concat(mapped, ignore_index=True).drop_duplicates()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build the locked 24 external predictors and T2D outcome from "
            "phenotype-mapped longitudinal tables"
        )
    )
    parser.add_argument("--patients", type=Path, required=True)
    parser.add_argument(
        "--encounters",
        type=Path,
        default=None,
        help=(
            "Preferred mode: encounter table with patient_id and encounter_date. "
            "Requires --non-adhd-random-seed and cohort in the patient table; "
            "the pipeline constructs both cohort landmarks."
        ),
    )
    parser.add_argument(
        "--non-adhd-random-seed",
        default=None,
        help="Site-defined seed recorded before non-ADHD landmark construction.",
    )
    parser.add_argument("--diagnoses", type=Path, required=True)
    parser.add_argument("--medications", type=Path, required=True)
    parser.add_argument("--medication-lookup", type=Path, required=True)
    parser.add_argument(
        "--medication-code-system",
        choices=("auto", "atc", "rxnorm"),
        default="auto",
        help=(
            "Medication input coding. 'auto' detects exactly one of atc_code "
            "or rxcui in the medication table."
        ),
    )
    parser.add_argument(
        "--phenotype-code-list",
        type=Path,
        default=None,
        help=(
            "Required when the diagnosis table contains code_system/code instead "
            "of a pre-mapped phenotype column."
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--audit-json",
        type=Path,
        default=None,
        help="Defaults to <output stem>_audit.json.",
    )
    args = parser.parse_args()

    patients = read_table(args.patients)
    encounters = read_table(args.encounters) if args.encounters is not None else None
    diagnoses = read_table(args.diagnoses)
    medications = read_table(args.medications)
    lookup = pd.read_csv(args.medication_lookup, dtype=str)
    require_columns(patients, PATIENT_REQUIRED, "patient table")
    if args.encounters is None:
        require_columns(patients, {"index_date"}, "patient table with preassigned landmarks")
        if args.non_adhd_random_seed is not None:
            raise ValueError("--non-adhd-random-seed is used only with --encounters")
    elif args.non_adhd_random_seed is None or not str(args.non_adhd_random_seed).strip():
        raise ValueError("--encounters requires a nonempty --non-adhd-random-seed")
    require_columns(diagnoses, DIAGNOSIS_BASE_REQUIRED, "diagnosis table")
    require_columns(medications, MEDICATION_BASE_REQUIRED, "medication table")
    medication_code_system, medication_code_column = medication_code_contract(
        medications, lookup, args.medication_code_system
    )

    if patients.patient_id.isna().any() or patients.patient_id.duplicated().any():
        raise ValueError("patient_id must be complete and unique in the patient table")
    for frame in (patients, diagnoses, medications):
        frame["patient_id"] = frame.patient_id.astype(str)
    if patients.patient_id.duplicated().any():
        raise ValueError("patient_id is not unique after conversion to string")
    for column in ("birth_date", "ehr_start_date", "ehr_end_date"):
        parse_date(patients, column)
    if "index_date" in patients:
        parse_date(patients, "index_date")
    if "death_date" not in patients:
        patients["death_date"] = pd.NaT
    else:
        parse_date(patients, "death_date")
    parse_date(diagnoses, "diagnosis_date")
    parse_date(medications, "start_date")
    diagnosis_rows_invalid_date = int(diagnoses.diagnosis_date.isna().sum())
    medication_rows_invalid_date = int(medications.start_date.isna().sum())
    if medication_code_system == "atc":
        medications[medication_code_column] = medications[medication_code_column].map(
            normalize_atc
        )
        lookup[medication_code_column] = lookup[medication_code_column].map(normalize_atc)
        invalid_atc = (
            medications[medication_code_column].ne("")
            & ~medications[medication_code_column].str.fullmatch(r"[A-Z][0-9]{2}[A-Z]{2}[0-9]{2}")
        )
        if invalid_atc.any():
            examples = sorted(
                medications.loc[invalid_atc, medication_code_column].unique()
            )[:10]
            raise ValueError(
                "ATC input must use exact fifth-level codes (for example C03AA03). "
                f"Invalid examples: {examples}"
            )
    else:
        medications[medication_code_column] = (
            medications[medication_code_column].astype(str).str.strip()
        )
        lookup[medication_code_column] = (
            lookup[medication_code_column].astype(str).str.strip()
        )
    if "phenotype" not in diagnoses:
        if args.phenotype_code_list is None:
            raise ValueError(
                "Diagnosis table has no phenotype column; provide --phenotype-code-list"
            )
        diagnoses = map_diagnosis_codes(diagnoses, args.phenotype_code_list)
    diagnoses["phenotype"] = diagnoses.phenotype.astype(str).str.strip().str.lower()

    audit = {
        "patients_input": int(len(patients)),
        "diagnosis_rows_input": int(len(diagnoses)),
        "medication_rows_input": int(len(medications)),
        "medication_code_system": medication_code_system,
        "obesity_ascertainment": (
            "diagnosis-only external approximation using approved codes; "
            "training also classified BMI >=30, but external BMI is unavailable"
        ),
        "diagnosis_rows_missing_or_invalid_date": diagnosis_rows_invalid_date,
        "medication_rows_missing_or_invalid_date": medication_rows_invalid_date,
        "diagnosis_rows_by_phenotype": {
            str(name): int(count)
            for name, count in diagnoses.phenotype.value_counts(dropna=False).items()
        },
        "diagnosis_rows_unrecognized_phenotype": int(
            (~diagnoses.phenotype.isin(list(LOCKED_DIAGNOSES) + ["dm2", LANDMARK_PHENOTYPE])).sum()
        ),
    }
    if encounters is not None:
        patients = construct_prediction_landmarks(
            patients,
            diagnoses,
            encounters,
            str(args.non_adhd_random_seed),
            audit,
        )
    else:
        audit["landmark_mode"] = "preassigned_index_date"
    required_dates_missing = patients[
        ["birth_date", "ehr_start_date", "ehr_end_date", "index_date"]
    ].isna().any(axis=1)
    audit["patients_dropped_missing_required_dates"] = int(required_dates_missing.sum())
    patients = patients.loc[~required_dates_missing].copy()

    invalid_chronology = (
        (patients.birth_date > patients.ehr_start_date)
        | (patients.ehr_start_date > patients.index_date)
        | (patients.birth_date > patients.index_date)
    )
    if invalid_chronology.any():
        raise ValueError(
            "Patient date chronology is invalid: require birth_date <= "
            "ehr_start_date <= index_date; bad rows="
            f"{int(invalid_chronology.sum())}"
        )

    patients["censor_date"] = patients.ehr_end_date
    use_death = patients.death_date.notna() & (patients.death_date < patients.censor_date)
    patients.loc[use_death, "censor_date"] = patients.loc[use_death, "death_date"]
    nonpositive_followup = patients.censor_date <= patients.index_date
    audit["patients_dropped_nonpositive_followup"] = int(nonpositive_followup.sum())
    patients = patients.loc[~nonpositive_followup].copy()

    undated_t2d_ids = set(
        diagnoses.loc[
            (diagnoses.phenotype == "dm2") & diagnoses.diagnosis_date.isna(),
            "patient_id",
        ]
    )
    audit["patients_dropped_t2d_record_without_usable_date"] = int(
        patients.patient_id.isin(undated_t2d_ids).sum()
    )
    patients = patients.loc[~patients.patient_id.isin(undated_t2d_ids)].copy()

    t2d = diagnoses[(diagnoses.phenotype == "dm2") & diagnoses.diagnosis_date.notna()].copy()
    t2d = t2d.merge(patients[["patient_id", "index_date"]], on="patient_id", how="inner")
    prior_t2d_ids = set(t2d.loc[t2d.diagnosis_date <= t2d.index_date, "patient_id"])
    audit["patients_dropped_t2d_on_or_before_landmark"] = int(
        patients.patient_id.isin(prior_t2d_ids).sum()
    )
    patients = patients.loc[~patients.patient_id.isin(prior_t2d_ids)].copy()

    output = patients.copy()
    output["age_index"] = (output.index_date - output.birth_date).dt.days / 365.25
    output["age_start"] = (output.ehr_start_date - output.birth_date).dt.days / 365.25
    output["months2index"] = (output.index_date - output.ehr_start_date).dt.days / 30.4375

    diagnoses_prior = diagnoses[
        diagnoses.phenotype.isin(LOCKED_DIAGNOSES) & diagnoses.diagnosis_date.notna()
    ].merge(output[["patient_id", "index_date", "birth_date"]], on="patient_id", how="inner")
    diagnoses_prior = diagnoses_prior[diagnoses_prior.diagnosis_date <= diagnoses_prior.index_date]
    first_diagnosis = (
        diagnoses_prior.groupby(["patient_id", "phenotype"], as_index=False)
        .diagnosis_date.min()
    )
    for phenotype in LOCKED_DIAGNOSES:
        selected = first_diagnosis[first_diagnosis.phenotype == phenotype][
            ["patient_id", "diagnosis_date"]
        ].rename(columns={"diagnosis_date": f"{phenotype}_date"})
        output = output.merge(selected, on="patient_id", how="left")
        output[phenotype] = output[f"{phenotype}_date"].notna().astype(np.uint8)
        output[f"{phenotype}_age"] = np.where(
            output[phenotype] == 1,
            (output[f"{phenotype}_date"] - output.birth_date).dt.days / 365.25,
            -1.0,
        )
        output.drop(columns=f"{phenotype}_date", inplace=True)

    marital = output.marital_status.astype("string").str.strip().str.lower()
    output["Marital_1"] = marital.eq("married").astype(np.uint8)
    output["Marital_2"] = marital.eq("single").astype(np.uint8)
    output["Marital_3"] = (~marital.isin(["married", "single"])).astype(np.uint8)

    locked_lookup = lookup[
        lookup.med_feature.isin(MEDICATION_CLASSES)
        & (lookup.primary_include.astype(str) == "1")
    ][[medication_code_column, "med_feature"]].drop_duplicates()
    medications_with_dates = medications[medications.start_date.notna()].copy()
    mapped_input = medications_with_dates.merge(
        locked_lookup, on=medication_code_column, how="inner"
    )
    audit["medication_rows_with_valid_dates"] = int(len(medications_with_dates))
    audit["medication_rows_matching_locked_lookup"] = int(len(mapped_input))
    audit["unique_input_medication_codes"] = int(
        medications_with_dates[medication_code_column].nunique()
    )
    audit["unique_input_medication_codes_matching_lookup"] = int(
        mapped_input[medication_code_column].nunique()
    )
    matched_codes = set(locked_lookup[medication_code_column])
    unmatched_medications = medications_with_dates.loc[
        ~medications_with_dates[medication_code_column].isin(matched_codes)
    ]
    audit["medication_rows_not_matching_locked_lookup"] = int(
        len(unmatched_medications)
    )
    if medication_code_system == "atc":
        unmatched_relevant = unmatched_medications[
            unmatched_medications[medication_code_column].str.startswith(
                ("C03", "C10"), na=False
            )
        ]
        audit["unmatched_c03_c10_rows"] = int(len(unmatched_relevant))
        audit["top_unmatched_c03_c10_codes"] = {
            str(code): int(count)
            for code, count in unmatched_relevant[medication_code_column]
            .value_counts()
            .head(25)
            .items()
        }
    medication = mapped_input.merge(
        output[["patient_id", "index_date"]], on="patient_id", how="inner"
    )
    medication = medication[medication.start_date < medication.index_date].copy()
    medication["in_1y"] = medication.start_date >= (
        medication.index_date - pd.to_timedelta(365, unit="day")
    )
    for med_class in MEDICATION_CLASSES:
        part = medication[medication.med_feature == med_class].copy()
        if len(part):
            aggregate = part.groupby("patient_id").agg(
                most_recent=("start_date", "max"),
                any_1y=("in_1y", "max"),
            ).reset_index()
            dates_1y = (
                part[part.in_1y]
                .groupby("patient_id").start_date.nunique()
                .rename("dates_1y")
                .reset_index()
            )
            aggregate = aggregate.merge(dates_1y, on="patient_id", how="left")
            output = output.merge(aggregate, on="patient_id", how="left")
        else:
            output["most_recent"] = pd.NaT
            output["any_1y"] = np.nan
            output["dates_1y"] = np.nan
        has_prior = output.most_recent.notna()
        output[f"rx_any_{med_class}"] = has_prior.astype(np.uint8)
        output[f"rx_1y_{med_class}"] = output.any_1y.fillna(False).astype(np.uint8)
        output[f"rx_dates1y_{med_class}"] = output.dates_1y.fillna(0).astype(int)
        output[f"rx_days_{med_class}"] = np.where(
            has_prior,
            (output.index_date - output.most_recent).dt.days,
            -100,
        )
        output[f"rx_days_{med_class}_miss"] = (~has_prior).astype(np.uint8)
        output.drop(columns=["most_recent", "any_1y", "dates_1y"], inplace=True)

    post_t2d = diagnoses[(diagnoses.phenotype == "dm2") & diagnoses.diagnosis_date.notna()].merge(
        output[["patient_id", "index_date", "censor_date"]], on="patient_id", how="inner"
    )
    post_t2d = post_t2d[
        (post_t2d.diagnosis_date > post_t2d.index_date)
        & (post_t2d.diagnosis_date <= post_t2d.censor_date)
    ]
    first_post_t2d = (
        post_t2d.groupby("patient_id", as_index=False).diagnosis_date.min()
        .rename(columns={"diagnosis_date": "first_post_t2d_date"})
    )
    output = output.merge(first_post_t2d, on="patient_id", how="left")
    output["dm2"] = output.first_post_t2d_date.notna().astype(np.uint8)
    analysis_end = output.first_post_t2d_date.fillna(output.censor_date)
    output["event_years"] = (analysis_end - output.index_date).dt.days / 365.25
    nonpositive_outcome_time = ~np.isfinite(output.event_years) | (output.event_years <= 0)
    audit["patients_dropped_missing_or_nonpositive_event_years"] = int(
        nonpositive_outcome_time.sum()
    )
    output = output.loc[~nonpositive_outcome_time].copy()

    validate_predictors(output, strict=True)
    optional = [name for name in ("cohort", "sex") if name in output]
    output["age_group"] = pd.cut(
        output.age_index,
        bins=[-np.inf, 17, 29, 44, 64, np.inf],
        labels=["<18", "18-29", "30-44", "45-64", "65+"],
    ).astype(str)
    final_columns = ["patient_id"] + FEATURE_NAMES + ["dm2", "event_years"] + optional + ["age_group"]
    output = output[final_columns]
    audit["patients_output"] = int(len(output))
    audit["patients_with_post_landmark_t2d"] = int(output.dm2.sum())
    audit["predictor_columns"] = FEATURE_NAMES
    audit["landmark_age_summary_by_cohort"] = {}
    if "cohort" in output:
        for cohort_value, part in output.groupby("cohort", dropna=False):
            ages = part.age_index.astype(float)
            audit["landmark_age_summary_by_cohort"][str(cohort_value)] = {
                "n": int(len(part)),
                "minimum": float(ages.min()),
                "p01": float(ages.quantile(0.01)),
                "median": float(ages.median()),
                "p99": float(ages.quantile(0.99)),
                "maximum": float(ages.max()),
                "age_lt_1": int((ages < 1).sum()),
                "age_1_to_4": int(((ages >= 1) & (ages < 5)).sum()),
                "age_5_to_11": int(((ages >= 5) & (ages < 12)).sum()),
                "age_12_to_17": int(((ages >= 12) & (ages < 18)).sum()),
                "age_18_plus": int((ages >= 18).sum()),
            }
    audit_path = args.audit_json or args.output.with_name(f"{args.output.stem}_audit.json")
    write_table(output, args.output)
    save_json(audit, audit_path)
    print(f"Built {len(output):,} external patient rows")
    print(f"Saved: {args.output}")
    print(f"Audit: {audit_path}")


if __name__ == "__main__":
    main()
