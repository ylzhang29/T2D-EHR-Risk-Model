# Cohort and prediction-landmark protocol

## Confirmed development-cohort definitions

### ADHD cohort

- ADHD was defined by ICD-10-CM F90 and descendants (including F90.0,
  F90.1, F90.2, F90.8, and F90.9) or ICD-9-CM 314.0 and descendants.
- The first recorded qualifying ADHD diagnosis defined the ADHD index date.
- The prediction landmark was 365 days after that first ADHD index date.

### Non-ADHD comparison cohort

- Patients had no qualifying ADHD diagnosis throughout their observable record,
  from the first through last known EHR date.
- One encounter of any encounter type was selected at random as the assigned
  prediction-landmark/index date.
- The external site must declare a fixed site-defined random seed before cohort
  construction and retain the seed and selected encounter so the assignment can
  be reproduced. The seed is a required site-level input, not a universal seed
  imposed by the coordinating center.
- If the site cannot sample from recorded encounters, it may describe an
  alternative randomly selected observable time. That alternative is a protocol
  deviation requiring coordinating-investigator approval before external
  outcomes are examined; it must not be substituted silently.

### Landmark eligibility and outcome

- Exclude a qualifying recorded T2D diagnosis on or before the prediction
  landmark.
- Exclude patients whose observable follow-up ends on or before the landmark.
- The event is the first qualifying recorded T2D diagnosis after the landmark
  and no later than the earlier of EHR end and death.
- The primary external evaluation uses the complete natural-frequency eligible
  cohort. Do not outcome-balance, match on future T2D, or sample according to
  outcome status.
- The outcome-balanced RF development sample was a separate modeling sample and
  is not the target external-validation population.

## Pre-landmark history and age

The audited downstream Stata pipeline did not enforce an explicit minimum
duration of pre-landmark EHR history. The cohort flowchart also does not specify
a minimum. Therefore, the current reproducible definition is **no additional
minimum pre-landmark duration**, provided `ehr_start_date <= index_date` and the
required predictors can be constructed.

No age restriction was applied to either the ADHD or non-ADHD development
cohort. The primary external validation must therefore retain all otherwise
eligible ages. Development summaries included landmark ages as low as about
1.1 years in ADHD and 0.1 years in non-ADHD patients. These low values require
data-quality review and careful interpretation, but they are not grounds for an
unplanned primary-analysis exclusion.

Before outcomes are examined, the site must report the minimum, 1st percentile,
median, 99th percentile, and maximum landmark age by cohort; counts aged <1,
1-4, 5-11, 12-17, and >=18 years; and any impossible date sequences. A
restricted-age sensitivity analysis may be added only if its cutoff is approved
and documented before outcome evaluation. The unrestricted cohort remains the
primary replication analysis.

## Site inputs required before cohort construction

1. Fixed site-defined random seed used for non-ADHD encounter selection:
   ____________________.
2. Confirmation that all encounter types are included: Yes / No. If no,
   describe the deviation: ____________________________________________.
3. Confirmation that encounters on the first or last observable EHR date are
   available for random selection: Yes / No. If no, describe the source rule:
   ____________________________________________________________________.
4. Confirmation that the site can implement the unrestricted-age primary
   cohort and return the prespecified age-quality summary: Yes / No.

Record these decisions before the external site constructs its cohort. Do not
change the landmark algorithm after examining external outcomes.
