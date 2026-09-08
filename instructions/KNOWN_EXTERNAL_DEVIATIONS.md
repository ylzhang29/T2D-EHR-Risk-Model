# Required deviation documentation

## Obesity

Development obesity used a qualifying diagnosis or BMI >=30 kg/m2 before the
prediction index. The supplied raw-data builder uses qualifying diagnosis
records only. Diagnosis-only ascertainment may undercount obesity.

Before outcome evaluation, record whether pre-index BMI is available, whether
its dates and units can reproduce the development definition, which obesity
rule will be used, and how any deviation will be reported.

Return:

- the selected obesity rule;
- percentage with `obesity=1`;
- percentage with qualifying ICD-10-CM E65-E66 records;
- percentage with qualifying ICD-9-CM 278.0-278.1 records, when applicable; and
- a statement describing BMI availability and any deviation.

Do not add BMI selectively after viewing model performance and do not
recalibrate the model as part of the primary external validation.

## Other deviations

Document any approved difference in cohort eligibility, index construction,
diagnosis coding, medication mapping, date precision, predictor construction,
outcome ascertainment, death capture, censoring, or subgroup availability.
