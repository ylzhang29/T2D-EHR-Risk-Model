# Site-prepared final table — Mode B

Provide one unique row per patient containing `patient_id`, `dm2`,
`event_years`, and the exact ordered variables for every selected model.

The site must attest that it followed the index, four baseline exclusions,
pre-index predictor windows, outcome, censoring, and natural-frequency rules.
The package validates names, values, sentinels, timing consistency, and each
bundle contract, but cannot reconstruct how the table was created.

Do not standardize, round, rename, reorder, or newly impute predictors. Use the
template that matches the selected model:

- `definitions/external_input_template_5group.csv`
- `definitions/external_input_template_10group.csv`

When scoring both models together, include the union of their predictor columns.
Use the examples and contracts in `definitions/`, `model/`, and `examples/`.
