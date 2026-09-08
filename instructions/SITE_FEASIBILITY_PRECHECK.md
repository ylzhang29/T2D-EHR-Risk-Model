# External-site feasibility precheck

Complete this short checklist before constructing the validation cohort or
examining outcomes. Refer to the root `README.md` for the full definitions.
Document any deviation before outcome evaluation.

## 1. Input pathway

Select one:

- [ ] **Mode A:** the package will construct the final table from longitudinal
  patient, diagnosis, and medication files.
- [ ] **Mode B:** the site will supply the final one-row-per-patient table with
  the exact 24 predictors, `dm2`, and `event_years`.

Encounter file available: Yes / No

If no, describe the source of the preassigned non-ADHD `index_date`:
___________________________________________________________________________

## 2. Cohort and index

- [ ] ADHD index can be defined as 365 days after the first qualifying ADHD
  diagnosis.
- [ ] Non-ADHD patients can be confirmed to have no qualifying ADHD diagnosis
  in their observable record.
- [ ] The non-ADHD index can be reproducibly selected without using future T2D
  status or post-index predictors.
- [ ] All otherwise eligible ages will be retained in the primary analysis.
- [ ] Recorded T2D on or before index can be excluded and follow-up after index
  can be established.

Site-defined random seed, when encounter sampling is used: _________________

Any cohort or index deviation: _____________________________________________

## 3. Predictor replication

- [ ] The site can reproduce the supplied diagnosis phenotypes and restrict
  predictor diagnoses to records on or before index.
- [ ] Diuretic and statin records can be restricted to dates strictly before
  index and mapped using the supplied medication lookup.

Available diagnosis coding systems and years: ______________________________

If ICD-9-CM is used for CVD ascertainment, crosswalk used to map from ICD-9-CM
to ICD-10-CM: ______________________________________________________________

ATC combination products are represented or decomposed at the ingredient
level: Yes / No / Not applicable

If no, describe the medication-mapping limitation: _________________________

Medication record type (for example, prescribed or dispensed): _____________

Obesity definition selected for this validation:

- [ ] qualifying diagnosis or pre-index BMI >=30 kg/m2
- [ ] diagnosis only; BMI is unavailable or unusable and the deviation will be
  reported

Any other predictor or date-precision deviation: ___________________________

## 4. Outcome and reporting

- [ ] The site can identify the first recorded T2D diagnosis after index and
  calculate censoring using EHR end and death date when available.
- [ ] The primary cohort will retain its natural outcome frequency; it will not
  be balanced or matched using future T2D status.
- [ ] Age and sex are available for the planned subgroup analyses, or their
  absence will be documented.
- [ ] Patient-level inputs, constructed predictors, and predictions will remain
  at the site; only disclosure-reviewed aggregate outputs will be returned.

Completed by/date: _________________________________________________________
