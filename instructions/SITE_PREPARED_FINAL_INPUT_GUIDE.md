# Site-prepared final table: Mode B

Use this mode when the external site will construct its own cohort, prediction
index, predictors, outcome, and censoring time. Follow the exact 24-predictor
table and quality checks in the root `README.md`.

The CSV or Parquet file must contain one unique row per patient with:

- complete, unique, deidentified `patient_id`;
- all 24 predictors in the locked names and order;
- `dm2` containing only `0` or `1`;
- complete `event_years > 0`; and
- optional `cohort`, `sex`, and `age_group`.

Do not standardize, round, rename, reorder, or newly impute predictors. Use
`-1` for the age of an absent diagnosis and `-100` plus `_miss=1` when no
qualifying prior medication record exists.

Start with:

- `examples/synthetic_site_prepared_final_input.csv`
- `examples/configs/final_table_input.synthetic.json`

Then run:

```bash
python src/run_from_config.py --config examples/configs/site_run_config.json
```

Schema validation cannot verify how the site constructed its table. Return an
attestation confirming that the locked cohort and index rules were followed,
predictors used no post-index information, baseline T2D was excluded, outcome
and censoring were constructed as specified, natural outcome frequency was
retained, and all material deviations were documented.
