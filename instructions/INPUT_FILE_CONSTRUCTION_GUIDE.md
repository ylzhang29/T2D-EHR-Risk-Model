# Longitudinal input files: Mode A

Use this mode when the package will construct the final model table. The root
`README.md` contains the complete cohort, predictor, outcome, and sentinel
definitions.

CSV and Parquet are accepted. Dates use `YYYY-MM-DD`. Patient IDs must be
deidentified, site-local, complete, and consistent across files.

| File | Required columns |
|---|---|
| Patient | `patient_id,birth_date,ehr_start_date,ehr_end_date,death_date,marital_status,cohort,sex` |
| Encounter | `patient_id,encounter_date` |
| Diagnosis, raw | `patient_id,code_system,code,diagnosis_date` |
| Diagnosis, pre-mapped | `patient_id,phenotype,diagnosis_date` |
| Medication, ATC | `patient_id,atc_code,start_date` |
| Medication, RxNorm | `patient_id,rxcui,start_date` |

For non-ADHD patients, the package deduplicates encounter dates and selects the
date with the lowest stable SHA-256 score derived from the declared site seed,
patient ID, and encounter date. This is reproducible and independent of input
row order.

If encounters are unavailable, add a documented `index_date` to the patient
file and omit encounter and seed settings. Document the source of every
non-ADHD index and confirm that future T2D status and post-index predictors were
not used.

Use the distributed phenotype and medication lookup files unchanged. Confirm
that dated medication records use the supplied ingredient-level codes and note
whether combination products are represented at the ingredient level. Select
and document the obesity definition. Synthetic inputs and configurations are
in `examples/`.

Run:

```bash
python src/run_from_config.py --config examples/configs/site_run_config.json
```

The pipeline audits columns, dates, patient uniqueness, landmark construction,
pre-index windows, medication-code matching, baseline T2D exclusions,
predictor consistency, outcome time, and cohort age distributions.
