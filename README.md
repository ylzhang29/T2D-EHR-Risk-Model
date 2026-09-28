# T2D EHR Risk Models

This repository provides saved EHR prediction models for independent external
validation of the five-year probability of a first recorded type 2 diabetes
(T2D) diagnosis. The outcome is a recorded diagnosis, not biological disease
onset.

## Choose a package

Use one package throughout a validation. Do not combine models, predictor
definitions, scripts, or templates across packages.

| Package | Use when | Models |
|---|---|---|
| [`t1d-retained-ehr/`](t1d-retained-ehr/) | Recorded T1D at the prediction date is retained | One 10-group EHR model |
| [`t1d-excluded-ehr/`](t1d-excluded-ehr/) | Recorded T1D and T2D, plus specified pre-index glycemic evidence, are excluded | 5-group and 10-group EHR models |

Read the selected package's README for its cohort rules, predictor definitions,
templates, and commands.

## Research use and data handling

These materials are for research and independent external validation only. They
are not medical devices and must not be used for individual clinical decisions.
See [RESEARCH_USE_NOTICE.md](RESEARCH_USE_NOTICE.md) for the full research-use
limitations.

Keep source data, derived patient tables, and individual predictions behind the
external site's firewall. Return only disclosure-reviewed aggregate results,
figures, audits, and run manifests. Apply local small-cell disclosure rules
before any transfer.

## Set up and test a package

Download or clone the complete repository, then work inside the selected
package directory. Each package has its own dependencies and verification
script.

```bash
cd t1d-excluded-ehr   # or: cd t1d-retained-ehr
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python 00_VERIFY_PACKAGE.py --run-synthetic-tests
```

On Windows PowerShell, activate the environment with
`.venv\Scripts\Activate.ps1`.

The synthetic test checks package hashes, saved-model and predictor-contract
matching, and all supported input pathways. It uses synthetic records only and
removes its temporary outputs automatically.

## Common workflow

1. Choose the package and read its README.
2. Use its model-requirement table and input template to confirm that the site
   can construct the required variables.
3. Run the included synthetic test.
4. Use either longitudinal inputs, so the package builds predictors, or a
   site-prepared final table with the exact required columns and sentinels.
5. An ADHD-only validation is permitted. A non-ADHD cohort is optional; when
   included, follow the selected package's index-date rules and retain its
   natural composition.
6. Prespecify decision thresholds before reviewing outcomes. Keep the cohort's
   natural event frequency; do not balance or select patients using future T2D.
7. Run the package configuration and return only the approved aggregate output
   directory.

The saved models and their transported calibration must not be refit, tuned, or
recalibrated for the primary external-validation analysis. Any local
recalibration is secondary and must be reported separately after the
transported result.

## Date preparation before creating input files

Use complete ISO dates (`YYYY-MM-DD`) whenever available. If the source has a
partial calendar date, convert it deterministically **before** creating the
package input files:

| Source precision | Required input date |
|---|---|
| Year only: `YYYY` | `YYYY-07-01` |
| Year and month: `YYYY-MM` | `YYYY-MM-15` |
| Full date: `YYYY-MM-DD` | Use the recorded date unchanged |

Apply the same rule consistently to every date field supplied to a package,
including birth date, EHR start/end dates, death date, diagnoses, encounters,
medication starts, laboratory results, and any preassigned index date. Do not
leave partial dates in the input files or apply different rules across people
or tables. Record the source date precision and this normalization in the
site's local construction documentation, and report it as a material deviation
when it could affect index timing, eligibility, predictor windows, or follow-up.
