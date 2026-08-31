# Known external predictor-definition deviation

## Obesity status

The development obesity indicator was positive when either:

1. A qualifying obesity/adiposity diagnosis was recorded before the prediction
   landmark (ICD-10-CM E65-E66 or ICD-9-CM 278.0-278.1); or
2. A pre-landmark BMI value was at least 30 kg/m2.

The external validation site may not have BMI. The external package therefore
constructs obesity status from qualifying diagnosis records only. Patients
without a recorded qualifying diagnosis receive `obesity=0` and
`obesity_age=-1`, but this does not establish absence of obesity.

This is a partial predictor-replication limitation and may cause systematic
underascertainment, especially if obesity is incompletely coded. Report it in
the primary external-validation methods and limitations. Do not impute BMI or
recalibrate the model using external outcomes as part of the primary analysis.

The external site should return:

- The percentage with `obesity=1`.
- The percentage with any E65-E66 diagnosis.
- The percentage with any ICD-9-CM 278.0-278.1 diagnosis, when applicable.
- A statement confirming that BMI was unavailable.

Before cohort construction, the site must answer:

1. Are measured BMI values available before the prediction landmark?
2. If yes, are units and dates sufficiently complete to reproduce BMI >=30
   kg/m2 as part of the development obesity definition?
3. If no, can the site reproduce the diagnosis-only definition using the
   supplied ICD-10-CM E65-E66 and ICD-9-CM 278.0-278.1 definitions?
4. Which definition will be used, and what deviation from development will be
   reported?

The answer must be locked before external outcomes are examined. Do not add BMI
selectively after viewing model performance.
