# T1D-Excluded EHR Models

This package lets an external site test two saved models that predict the
five-year probability of a first recorded type 2 diabetes (T2D) diagnosis.
Both models apply the same diabetes-free eligibility rules at the prediction
date.

For setup, synthetic testing, research-use limitations, privacy requirements,
and the common validation workflow, read the repository [README](../README.md)
first.

## Models

| Selection name | Model | Predictors |
|---|---|---:|
| `compact5` | 5-group EHR model | 15 |
| `compact10` | 10-group EHR model | 19 |

The saved bundles contain the fitted random forest, predictor order, and frozen
calibration. Do not refit, tune, or recalibrate them for the primary external
validation. The package checks that the selected model and predictor contract
match before scoring.

## Predictors at a glance

Use this table to determine whether the site can run the 5-group model, the
10-group model, or both. Exact definitions, dates, and sentinel values are in
the model-requirement tables and predictor dictionary.

| Predictor | 5-group | 10-group | Source type |
|---|:---:|:---:|---|
| `age_index` | Yes | Yes | Patient dates |
| `age_start` |  | Yes | Patient dates |
| `months2index` |  | Yes | Patient dates |
| `depress` | Yes |  | Diagnosis |
| `depress_age` | Yes |  | Diagnosis + birth date |
| `PDD` |  | Yes | Diagnosis |
| `PDD_age` |  | Yes | Diagnosis + birth date |
| `gestationaldm` |  | Yes | Diagnosis |
| `gestationaldm_age` |  | Yes | Diagnosis + birth date |
| `hf` |  | Yes | Diagnosis |
| `hf_age` |  | Yes | Diagnosis + birth date |
| `obesity` | Yes | Yes | Diagnosis |
| `obesity_age` | Yes | Yes | Diagnosis + birth date |
| `sleep` |  | Yes | Diagnosis |
| `sleep_age` |  | Yes | Diagnosis + birth date |
| `smoking_proxy_diagnosis` |  | Yes | Diagnosis-code proxy |
| `rx_any_lipid_statin` | Yes |  | Dated statin prescription |
| `rx_1y_lipid_statin` | Yes |  | Dated statin prescription |
| `rx_dates1y_lipid_statin` | Yes |  | Dated statin prescription |
| `rx_days_lipid_statin` | Yes |  | Dated statin prescription |
| `rx_days_lipid_statin_miss` | Yes |  | Dated statin prescription |
| `rx_any_mood_antiep` | Yes | Yes | Dated mood-stabilizing/antiepileptic prescription |
| `rx_1y_mood_antiep` | Yes | Yes | Dated mood-stabilizing/antiepileptic prescription |
| `rx_dates1y_mood_antiep` | Yes | Yes | Dated mood-stabilizing/antiepileptic prescription |
| `rx_days_mood_antiep` | Yes | Yes | Dated mood-stabilizing/antiepileptic prescription |
| `rx_days_mood_antiep_miss` | Yes | Yes | Dated mood-stabilizing/antiepileptic prescription |

The 5-group model requires 15 predictors; the 10-group model requires 19.
Testing both requires the 26 unique predictors shown above. Medication
prescriptions must be dated and mapped with the supplied ATC or RxNorm lookup.

## Who should be included

There is no age restriction. The prediction date is:

- ADHD: 365 days after the first qualifying ADHD diagnosis.
- No ADHD: a reproducibly selected encounter date, or a documented
  encounter-equivalent date if encounter data are unavailable.

Exclude patients with any of the following on or before the prediction date:

- recorded T2D;
- recorded T1D;
- an undated source record indicating T2D; or
- diabetic-range HbA1c or verified fasting glucose on at least two distinct
  dates.

Retain prior gestational diabetes. Do not use medication evidence to exclude a
patient or define the outcome. Keep the cohort's natural event frequency; do
not balance or match patients using future T2D.

The outcome is the first recorded T2D diagnosis after the prediction date.
Follow-up ends at that diagnosis, the end of the available EHR record, or death,
whichever applies first. The analysis accounts for follow-up shorter than five
years.

## Choose an input method

### Option A: provide longitudinal files

| File | Required columns |
|---|---|
| Patients | Required: `patient_id,birth_date,ehr_start_date,ehr_end_date,cohort,undated_t2d_source_positive`; optional: `death_date,sex` |
| Encounters | `patient_id,encounter_date` |
| Diagnoses | `patient_id,code_system,code,diagnosis_date` |
| Labs | `patient_id,loinc_code,result_date,result_value,result_unit,fasting_verified` |
| ATC medications | `patient_id,atc_code,start_date` |
| RxNorm medications | `patient_id,rxcui,start_date` |

Dates use `YYYY-MM-DD`. Use deidentified site-local patient IDs. The package
constructs eligibility, predictors, outcome, and follow-up.

Set `undated_t2d_source_positive` to `1` only when another source table or
registry indicates T2D for that person but does not provide a usable diagnosis
date; otherwise set it to `0`. `death_date` may be blank when unavailable.

Start with:

```bash
python src/run_from_config.py \
  --config examples/configs/longitudinal_input.synthetic.json
```

If encounters are unavailable, provide `index_date` in the patient file and
use `examples/configs/no_encounter_input.synthetic.json`.

### Option B: provide the final model table

The site may instead create one row per patient containing:

- `patient_id`;
- the predictors required by each selected model;
- `dm2` (`0` or `1`); and
- `event_years`.

Optional subgroup columns are `cohort`, `sex`, and `age_group`. Exact predictor
definitions, including the required sentinel values, are in
`definitions/predictor_dictionary.csv`; examples are under `examples/`.

```bash
python src/run_from_config.py \
  --config examples/configs/final_table_input.synthetic.json
```

Do not standardize, rename, round, reorder, or newly impute predictors. The site
must confirm that it followed the eligibility, timing, outcome, and censoring
rules because the package cannot reconstruct a site-prepared table.

Use the template that matches the selected model:

- `definitions/external_input_template_5group.csv`
- `definitions/external_input_template_10group.csv`
- `definitions/external_input_template_both_models.csv`

To test both models in one final-table run, use
`external_input_template_both_models.csv`. It contains the 26 unique predictor
columns required across both models, plus `patient_id`, `dm2`, `event_years`,
and optional subgroup columns. Do not submit separate 5-group and 10-group
tables in the same run.

Set the configuration to:

```json
"model_variants": ["compact5", "compact10"]
```

The supplied `examples/configs/final_table_input.synthetic.json` already uses
this setting and the synthetic final table has the same combined structure.
For longitudinal input, the package constructs this combined predictor table
automatically when both variants are selected.

## Predictor timing

- Diagnoses: on or before the prediction date.
- Medication prescription starts: strictly before the prediction date.
- Prior-year medication window: day −365 through day −1.
- `smoking_proxy_diagnosis`: a diagnosis-code proxy, not observed smoking status.

Medication records do not prove dispensing, adherence, continuous use, or
treatment duration. ATC records must use the supplied fifth-level ingredient
codes. Decompose combination products into ingredient records before matching.

Before examining outcomes, confirm that the selected model's variables can be
constructed, the four baseline exclusions can be applied, medication starts
can be dated, and patient-level data will remain local. Document any material
deviation in the returned aggregate materials.

### Phenotype lists

Use `definitions/phenotype_code_list_REQUIRED.csv` with the longitudinal
builder. It is the operational combined list: it includes the shared ADHD,
T1D, and T2D eligibility phenotypes and all predictor phenotypes needed when
both models are tested.

For feasibility review and site mapping, each model has a self-contained
predictor requirement table. Each row identifies the model group, exact
variable name, necessary source data, timing rule, and required sentinel:

- `definitions/model_requirements_5group.csv`
- `definitions/model_requirements_10group.csv`

These tables do not replace the combined operational phenotype list, because
they do not include the shared ADHD, T1D, and T2D eligibility definitions.

## Select one or both models

In the JSON configuration:

```json
"model_variants": ["compact5", "compact10"]
```

To test one model, list only its selection name.

## Results

The package reports discrimination, calibration, decision-curve analysis, and
clinical-impact results with patient-level bootstrap confidence intervals.

```text
external_validation_output/
├── LOCAL_ONLY_DO_NOT_RETURN/
│   ├── external_model_input.parquet
│   └── external_patient_scores.parquet
└── RETURN_TO_COORDINATING_CENTER/
    ├── run_manifest.json
    ├── external_model_input_audit.json
    └── summary_results/
```

Follow the repository-level privacy and output-handling rules. The primary
analysis reports the frozen transported calibration. If local recalibration is
performed, label it as a secondary analysis and do not replace the primary
result.

No independent external-validation results are available until an external
site completes this process.
