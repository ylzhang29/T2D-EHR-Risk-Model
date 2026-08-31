# T2D EHR Risk Model

This is the single operating guide for an external partner. It covers package
verification, study definitions, both supported input modes, execution, output
handling, and the files that may be returned.

## Research-use notice

This repository is provided for research and independent external validation.
It is not a medical device, has not been established for clinical decision
making, and must not be used to diagnose, treat, or determine care for an
individual. Outputs require local validation and qualified scientific
interpretation. The software and model are provided without warranties. See
`RESEARCH_USE_NOTICE.md` before use.

## 1. Purpose and model supplied

The package deploys a random-forest model trained using EHR data to
predict the probability of a first recorded type 2 diabetes diagnosis within
five years after a defined prediction landmark.

Use only:

`model/rf_external_10group_5y_calibrated.joblib`

This saved bundle contains the trained `RandomForestClassifier`, the locked 24
predictors in their required order, and validation-fitted logistic calibration.
The model must not be refitted, tuned, or recalibrated for the primary external
validation. The outcome is first recorded T2D, not biological disease onset.

The distributed bundle does not contain patient identifiers, patient-level
training records or predictions, or internal computer paths. It retains only
the fitted model parameters and metadata required to calculate predictions.

## 2. Repository layout

```text
T2D-EHR-Risk-Model/
├── README.md                  Main operating guide
├── RESEARCH_USE_NOTICE.md     Intended-use limitations
├── requirements.txt           Python dependencies
├── 00_VERIFY_PACKAGE.py       Integrity and synthetic test runner
├── model/                     Saved model and model manifest
├── src/                       Python programs
├── examples/                  Synthetic input tables and configurations
├── definitions/               Predictor, outcome, phenotype, and medication definitions
└── instructions/              Detailed construction and output guidance
```

Important files:

- `model/rf_external_10group_5y_calibrated.joblib`: saved deployment model.
- `model/rf_external_10group_manifest.json`: model provenance and feature contract.
- `00_VERIFY_PACKAGE.py`: portable integrity/model verification.
- `PACKAGE_SHA256SUMS.txt`: hashes for distributed files.
- `src/run_external_validation.py`: complete command-line workflow.
- `src/run_from_config.py`: recommended JSON wrapper.
- `src/score_saved_model.py`: schema validation and scoring.
- `src/evaluate_external_validation.py`: metrics, calibration, DCA/CIC, plots.
- `src/build_external_model_input.py`: optional raw-data builder.
- `src/external_rf_common.py`: shared locked definitions and metrics.

Most users should run only `src/run_from_config.py`. It calls the other
components automatically.

## 3. Before using external data

Complete `instructions/SITE_FEASIBILITY_PRECHECK.md` and lock:

1. Available coding systems and phenotype definitions.
2. Non-ADHD site seed and encounter availability.
3. ATC combination-product/ingredient handling.
4. Obesity replication and the BMI limitation.
5. Age and sex subgroup availability.
6. The downstream action and prespecified risk thresholds.

Primary cohort rules:

- No age restriction for ADHD or non-ADHD patients.
- ADHD index: first qualifying ADHD diagnosis.
- ADHD prediction landmark: 365 days after that diagnosis.
- Non-ADHD: no qualifying ADHD diagnosis anywhere in the observable record.
- Non-ADHD landmark: seeded random selection among unique encounter dates of any type.
- Exclude recorded T2D on or before the prediction landmark.
- Require observable follow-up after the landmark.
- Use the natural-frequency cohort; do not outcome-balance or match on future T2D.

## 4. Install and verify

Use Python 3.8 when possible:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python 00_VERIFY_PACKAGE.py
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

For a complete technical demonstration using only synthetic records:

```bash
python 00_VERIFY_PACKAGE.py --run-synthetic-tests
```

The verifier checks every distributed hash, parses every Python script, loads
the saved model, verifies the 24-feature order, verifies the frozen five-year
calibration, and optionally executes all three supported workflows.

## 5. Choose one input mode

### Mode A — package constructs the final table

Use this mode when the site can provide longitudinal source tables.

Patient file, one row per patient:

`patient_id,birth_date,ehr_start_date,ehr_end_date,death_date,marital_status,cohort,sex`

Encounter file, one row per encounter:

`patient_id,encounter_date`

Diagnosis file, raw-code form:

`patient_id,code_system,code,diagnosis_date`

Medication file:

- ATC: `patient_id,atc_code,start_date`
- RxNorm: `patient_id,rxcui,start_date`

Dates use `YYYY-MM-DD`. Patient IDs must be deidentified site-local identifiers.
Do not include names, medical-record numbers, addresses, or direct identifiers.

The builder constructs landmarks, predictor dates, medication variables,
prevalent-T2D exclusions, outcome, censoring time, and age groups. The site seed
is recorded in the manifest and audit.

#### If the site has no encounter file

The longitudinal-table route can still be used if the site supplies an approved
`index_date` in the one-row-per-patient file. In this mode:

- omit `encounters` and `non_adhd_random_seed` from the configuration;
- add `index_date` to the patient file;
- retain the ADHD rule of 365 days after the first qualifying ADHD diagnosis;
- document how each non-ADHD index date was selected; and
- complete the no-encounter section of the feasibility precheck.

Preferred substitutes for the non-ADHD date are, in order: a site-generated
encounter-equivalent date; a seeded selection from unique dates in a frozen
union of qualifying clinical-event tables; or a previously constructed index
date from the site's approved cohort pipeline. A uniformly sampled calendar
date between EHR start and end is not recommended because it may fall during an
inactive-care interval. Any substitute is a protocol deviation and must be
locked before external outcomes are examined.

Use `examples/configs/no_encounter_input.synthetic.json` as the configuration
example for this pathway. The supplied `examples/example_patient_shell.csv`
demonstrates the required patient table with preassigned index dates.

Synthetic inputs are under `examples/`:

- `synthetic_raw_patients.csv`
- `synthetic_raw_encounters.csv`
- `synthetic_raw_diagnoses.csv`
- `synthetic_raw_medications_atc.csv`

Copy `examples/configs/encounter_input.synthetic.json` to
`examples/configs/site_run_config.json`, replace the paths and example seed, and
run:

```bash
python src/run_from_config.py \
  --config examples/configs/site_run_config.json
```

### Mode B — site supplies the final model table

Use this mode when the site prefers to construct the cohort, landmarks,
predictors, outcome, and censoring variables itself.

The final CSV or Parquet file must contain one unique row per patient, the exact
24 predictors in `definitions/predictor_dictionary.csv`, plus:

- `patient_id`
- `dm2` (0/1)
- `event_years` (>0)
- optional `cohort`, `sex`, and `age_group`

Do not standardize or newly impute predictors. Use `-1` for age of an absent
diagnosis and `-100` plus missing indicator 1 for absent medication recency.

Full synthetic example:

`examples/synthetic_site_prepared_final_input.csv`

Copy `examples/configs/final_table_input.synthetic.json` to
`examples/configs/site_run_config.json`, replace the input and output paths, and
run `src/run_from_config.py` as above.

In Mode B, the package validates schema, values, feature order, outcome, and
follow-up, but cannot verify how the site constructed them. The site must return
an attestation confirming that the locked landmark, predictor-window, outcome,
censoring, and natural-frequency rules were followed.

## 6. Locked outcome and censoring

```text
censor_date = earlier of ehr_end_date and death_date
dm2 = 1 when index_date < first_t2d_date <= censor_date; otherwise 0
analysis_end = first_t2d_date when dm2=1; otherwise censor_date
event_years = (analysis_end - index_date) / 365.25
```

At five years, earlier censoring is handled with inverse-probability-of-
censoring weights rather than treated as a confirmed non-event. Death is treated
as censoring, not as a modeled competing risk.

## 7. Locked predictor rules

The ten groups are age at landmark, age at EHR start, any CVD, EHR history,
hypertension, diuretic medication history, type 1 diabetes, marital status,
statin medication history, and obesity. Together they produce 24 variables.

- Predictor diagnoses: first qualifying record on/before landmark.
- Medications: qualifying record strictly before landmark.
- Medication records do not establish dispensing or adherence.
- Absent diagnosis age: `-1`.
- Absent medication recency: `-100`; corresponding missing flag: `1`.
- Marital status: Married, Single, or Unknown indicators.
- Do not rename, reorder, standardize, refit, or impute the locked variables.

The development obesity definition used diagnosis or BMI >=30. If BMI is not
available externally, diagnosis-only obesity is a documented replication
limitation and must be reported.

## 8. Prespecified analysis

- Primary probability: validation-calibrated five-year risk.
- Metrics: ROC AUC, average precision, Brier score, calibration intercept and
  slope, observed/expected ratio, and calibration table/plot.
- Confidence intervals: patient-level bootstrap; recommended 500 replicates.
- Planned subgroups: sex and age group; no race/ethnicity subgroup analysis.
- Optional descriptive subgroup: ADHD cohort when available.
- Proposed DCA/CIC thresholds: 0.5%, 1%, 2%, 3%, 5%, 7.5%, and 10%.

Thresholds must correspond to a stated clinical action and resource burden and
must be locked before external outcomes are examined.

## 9. Output locations and privacy

```text
external_validation_output/
├── LOCAL_ONLY_DO_NOT_RETURN/
│   ├── external_model_input.parquet       Mode A only
│   ├── external_patient_scores.parquet
│   └── .matplotlib/
└── RETURN_TO_COORDINATING_CENTER/
    ├── run_manifest.json
    ├── external_model_input_audit.json
    └── summary_results/
        ├── external_metrics.json
        ├── external_bootstrap_metrics.csv
        ├── external_calibration.csv
        ├── external_subgroup_metrics.csv   when estimable
        ├── external_roc_curve.csv
        ├── external_pr_curve.csv
        ├── external_decision_curve.csv     when thresholds supplied
        ├── external_clinical_impact.csv    when thresholds supplied
        └── figures
```

Original inputs, constructed patient-level predictors, and patient-level raw or
calibrated predictions remain behind the site's firewall. Never return them
without separate authorization.

The site may return only `RETURN_TO_COORDINATING_CENTER`, the completed
feasibility precheck, the Mode B attestation when applicable, and a description
of approved deviations. The site must apply its disclosure policy to small cells
before returning aggregate files.

## 10. What success looks like

The console should end with:

```text
External validation completed successfully.
LOCAL ONLY — do not return: .../LOCAL_ONLY_DO_NOT_RETURN
SAFE RETURN DIRECTORY: .../RETURN_TO_COORDINATING_CENTER
```

Before transfer, the site analyst should confirm:

- `run_manifest.json` records the expected model hash, input hashes, mode,
  thresholds, subgroups, software, and seed when applicable.
- `external_model_input_audit.json` contains plausible cohort/exclusion counts.
- No patient-level file appears in the return directory.
- Every deviation is documented.
- Small aggregate cells have been reviewed under local disclosure rules.
