# How to construct the external-validation input files

CSV and Parquet are accepted. Use ISO dates (`YYYY-MM-DD`). Keep all files at
the external site; do not send patient-level inputs to the coordinating center.

## Preferred mode: let the package construct landmarks

### 1. Patient file — one row per patient

Required columns:

| Column | Meaning |
|---|---|
| `patient_id` | Deidentified site-local identifier; complete and unique |
| `birth_date` | Date of birth |
| `ehr_start_date` | First observable EHR date under the approved protocol |
| `ehr_end_date` | Last observable EHR date under the same protocol |
| `death_date` | Death date when available; blank otherwise |
| `marital_status` | `Married`, `Single`, or other/blank (mapped to Unknown) |
| `cohort` | `1`/`ADHD` or `0`/`non-ADHD` |
| `sex` | Harmonized site value used only for subgroup reporting |

Do not include names, medical-record numbers, addresses, or direct identifiers.
See `examples/synthetic_raw_patients.csv`.

### 2. Encounter file — one row per encounter

Required: `patient_id`, `encounter_date`. Optional columns such as
`encounter_type` are retained only in the source file and are not modeled.

All encounter types are eligible. For non-ADHD patients, the program removes
duplicate patient/date combinations, calculates a stable SHA-256 pseudo-random
score from `seed + patient_id + encounter_date`, and selects the lowest-scoring
date. The selected date is therefore reproducible and independent of input row
order. Record the site-defined seed before construction.

### 3. Diagnosis file — longitudinal rows

Raw-code format:

`patient_id, code_system, code, diagnosis_date`

Use the supplied phenotype code list. The program derives the first ADHD date,
the four pre-landmark predictor diagnoses, prevalent T2D exclusion, and the
first post-landmark T2D outcome. Alternatively, the site may provide a
pre-mapped `phenotype` column with values `adhd_landmark`, `cvd_any`, `hypert`,
`dm1`, `obesity`, or `dm2`.

### 4. Medication file — longitudinal rows

ATC: `patient_id, atc_code, start_date`

RxNorm: `patient_id, rxcui, start_date`

ATC must use exact fifth-level codes. Confirm before extraction whether
combination products are expanded to ingredient records. Medication records are
used only when strictly before the prediction landmark.

## Landmark definitions

- ADHD: first qualifying ADHD diagnosis plus 365 days.
- Non-ADHD: seeded random selection among unique eligible encounter dates.
- A non-ADHD patient with any qualifying ADHD diagnosis is excluded.
- An ADHD patient without a usable qualifying ADHD date is excluded.

## Compatibility mode: site-preassigned landmarks

If the site has already implemented and approved the landmark protocol, omit
`--encounters` and the seed, and add `index_date` to the patient file. The
package will audit but not reconstruct that landmark.

## Data checks performed automatically

- Patient IDs complete and unique.
- Required columns and usable dates.
- Birth <= EHR start <= landmark.
- Positive observable follow-up after landmark.
- T2D absent on/before landmark.
- Predictor diagnoses restricted to on/before landmark.
- Medications restricted to strictly before landmark.
- Locked 24-variable names, order, types, and sentinels.
- Cohort-specific age summaries and landmark-construction counts.

The synthetic files intentionally include one non-ADHD patient with an ADHD
diagnosis and one ADHD patient without an ADHD diagnosis so the exclusion audit
can be inspected.
