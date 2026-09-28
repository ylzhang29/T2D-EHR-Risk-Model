# Longitudinal input files — Mode A

Use the six file schemas in the root README. CSV and Parquet are accepted;
dates use `YYYY-MM-DD`; identifiers are deidentified and consistent across files.

The laboratory file must retain units and a verified fasting indicator. Only
HbA1c and verified fasting glucose contribute to the repeated diabetic-range
baseline exclusion. Medication records do not contribute to eligibility or the
outcome.

Use the supplied phenotype and medication lookups unchanged. For Mode A,
`phenotype_code_list_REQUIRED.csv` is the combined operational list. The
separate 5-group and 10-group model-requirement tables are feasibility and
mapping aids and do not include the shared eligibility definitions. Diagnosis predictors use
records on/before index; medication predictors use prescription starts strictly
before index. The package constructs the union of both model contracts, then
each selected model reads only its own ordered predictors.

Start with `examples/configs/longitudinal_input.synthetic.json`.
