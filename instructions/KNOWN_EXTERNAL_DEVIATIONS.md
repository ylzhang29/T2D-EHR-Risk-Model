# Required deviation documentation

## Obesity

Development obesity used a qualifying diagnosis or BMI >=30 kg/m2 before the
prediction index. The supplied raw-data builder uses qualifying diagnosis
records only. Diagnosis-only ascertainment may undercount obesity.

Record whether dated pre-index BMI is available and which obesity rule will be
used. If BMI cannot be incorporated, document use of the diagnosis-only rule as
a deviation. No separate code-specific frequency audit is required.

Do not add BMI selectively after viewing model performance and do not
recalibrate the model as part of the primary external validation.

## Other deviations

Document any difference in cohort eligibility, index construction,
diagnosis coding, medication mapping, date precision, predictor construction,
outcome ascertainment, death capture, censoring, or subgroup availability.
