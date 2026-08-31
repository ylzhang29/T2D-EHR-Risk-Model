# External-site feasibility precheck

Complete this document before cohort construction or review of external outcome
results. A "No" answer does not automatically prevent validation, but any
deviation must be reviewed and locked before outcomes are examined.

## Cohort and landmark

1. Can the site identify the first qualifying ADHD diagnosis and assign the
   ADHD prediction landmark 365 days later? Yes / No
2. Can the site identify patients with no qualifying ADHD diagnosis anywhere in
   their observable record? Yes / No
3. Can the site randomly select one encounter of any type as the non-ADHD
   prediction landmark? Yes / No
4. Site-defined fixed random seed, declared before construction: ____________
5. Are all encounter types eligible? Yes / No. If no, describe: _____________
6. Are encounters on the first and last observable EHR dates eligible for
   sampling? Yes / No. If no, describe: ____________________________________
7. Is a patient-level encounter file available? Yes / No
8. If no, can the site supply a preassigned `index_date` for every patient?
   Yes / No
9. Source of the non-ADHD preassigned date: encounter-equivalent date / seeded
   union of qualifying clinical-event dates / approved existing cohort date /
   other: _________________________________________________________________
10. If clinical-event dates are substituted for encounters, list every included
    table/event type and confirm the list was frozen before outcome review:
    _______________________________________________________________________
11. Confirm that a uniformly sampled calendar date during an inactive-care
    interval will not be used for the primary analysis: Yes / No
12. Site attestation that the preassigned dates were constructed without using
    future T2D status or post-landmark predictors: Yes / No

## Age and data quality

13. Can the site retain all otherwise eligible ages for the unrestricted primary
   analysis? Yes / No
14. Can the site return landmark-age summaries by ADHD cohort: minimum, 1st
   percentile, median, 99th percentile, maximum, and counts aged <1, 1-4, 5-11,
   12-17, and >=18 years? Yes / No
15. Can the site identify impossible sequences such as birth after landmark,
    EHR start after landmark, or EHR end on/before landmark? Yes / No

## Diagnosis phenotypes

16. Can the site reproduce the supplied ADHD, CVD, hypertension, type 1
    diabetes, obesity, and type 2 diabetes phenotype definitions? Yes / No
17. Which ICD systems and calendar periods are available? ___________________
18. Can all four predictor diagnosis dates be restricted to records on or before
    the landmark? Yes / No
19. Can T2D on/before landmark be excluded and the first post-landmark T2D date
    be identified? Yes / No
20. Investigator approval of the supplied phenotype code list: ______________

## Medication records

21. Does the ATC source expand combination products to active-ingredient
    records, so single and combination products both contribute ingredient
    records? Yes / No / Unknown
22. If no, can the site implement a frozen ingredient decomposition before
    outcomes are examined? Yes / No
23. Can the site return counts of valid fifth-level ATC rows, matched lookup
    rows, unmatched C03/C10 codes, and combination products? Yes / No

## Obesity replication

24. Is pre-landmark measured BMI available? Yes / No
25. If yes, can BMI units and dates support the development definition of a
    qualifying diagnosis or BMI >=30 kg/m2? Yes / No
26. If no, can diagnosis-only obesity be constructed using E65-E66 and
    278.0-278.1, and documented as a deviation? Yes / No
27. Locked obesity definition for this validation: __________________________

## Analysis outputs

28. Can the site provide sex and derived age group for subgroup summaries?
    Yes / No
29. Planned subgroups: age group and sex. Race and ethnicity are not planned.
    Confirm: Yes / No
30. Optional descriptive ADHD-cohort subgroup available: Yes / No
31. Intended action triggered by a high-risk classification: ________________
32. Are 0.5%, 1%, 2%, 3%, 5%, 7.5%, and 10% acceptable prespecified five-year
    risk thresholds for that action and workload? Yes / No. If no, propose and
    justify a threshold set before outcomes are examined: ___________________

## Approval

Site lead/date: _____________________________________________________________

Coordinating investigator/date: ____________________________________________
