# Optional site-prepared final-input mode

Use this mode when the external site prefers to construct its own cohort,
landmarks, predictors, outcome, and censoring variables. The package then
validates the final schema, applies the frozen model and calibration, and
creates the same separated local/return output structure.

## Important limitation

The package cannot independently verify how a site-prepared final table was
constructed. The site must complete the feasibility precheck and attest that it
followed the locked cohort, landmark, predictor-window, outcome, and censoring
protocol. Schema validation is not a substitute for that attestation.

## File format

CSV or Parquet is accepted. There must be one row per patient and a complete,
unique deidentified `patient_id`.

Required non-predictor columns:

- `patient_id`
- `dm2`: 1 for first recorded T2D after landmark and on/before censoring; 0 otherwise
- `event_years`: event or censoring time after landmark, complete and >0

Optional subgroup columns:

- `cohort`
- `sex`
- `age_group`

Required model predictors, in the locked contract:

1. `age_index`
2. `age_start`
3. `cvd_any`
4. `cvd_any_age`
5. `months2index`
6. `hypert`
7. `hypert_age`
8. `rx_any_htn_diuretic`
9. `rx_1y_htn_diuretic`
10. `rx_dates1y_htn_diuretic`
11. `rx_days_htn_diuretic`
12. `rx_days_htn_diuretic_miss`
13. `dm1`
14. `dm1_age`
15. `Marital_1`
16. `Marital_2`
17. `Marital_3`
18. `rx_any_lipid_statin`
19. `rx_1y_lipid_statin`
20. `rx_dates1y_lipid_statin`
21. `rx_days_lipid_statin`
22. `rx_days_lipid_statin_miss`
23. `obesity`
24. `obesity_age`

Do not standardize or impute these variables. Use `-1` for the age of an absent
diagnosis and `-100` for medication recency when no qualifying prior medication
record exists. The corresponding missing-recency indicator must equal 1.

See `definitions/predictor_dictionary.csv` for every definition and
`examples/synthetic_site_prepared_final_input.csv` for a complete example.

## Configuration

Copy `examples/configs/final_table_input.synthetic.json` to
`examples/configs/site_run_config.json` and replace the input/output paths. Do
not include raw patient, encounter, diagnosis, medication, lookup, or
random-seed fields in this mode.

```bash
python src/run_from_config.py \
  --config examples/configs/site_run_config.json
```

Equivalent command:

```bash
python src/run_external_validation.py \
  --model model/rf_external_10group_5y_calibrated.joblib \
  --final-input site_final_model_input.parquet \
  --output-dir external_validation_output \
  --bootstrap 500 \
  --subgroups "sex,age_group" \
  --decision-thresholds "0.005,0.01,0.02,0.03,0.05,0.075,0.10"
```

The original final input and generated patient-level scores remain local. Only
the aggregate return directory should be sent to the coordinating center.

## Required site attestation

The site should return a signed statement confirming that:

- ADHD and non-ADHD eligibility followed the locked protocol.
- The declared random seed and encounter selection were used for non-ADHD patients.
- ADHD landmarks were 365 days after the first qualifying ADHD diagnosis.
- Predictor diagnoses and medications used no post-landmark information.
- T2D on/before landmark was excluded.
- Event/censoring time used the earlier of EHR end and death.
- No outcome balancing or future-outcome matching was used.
- Obesity and combination-medication deviations were documented.
