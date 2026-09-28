# T2D EHR Risk Models

This repository contains separate, self-contained packages for independent
external validation of saved models that predict the five-year probability of a
first recorded type 2 diabetes (T2D) diagnosis from EHR data.

Choose one package and follow its own `README.md`. Do not combine its model,
predictor definitions, or scripts with those from another package.

| Package | Cohort definition | Contents |
|---|---|---|
| [`t1d-retained-ehr/`](t1d-retained-ehr/) | Does not exclude recorded T1D at the prediction date | Saved EHR model, predictor contract, and validation workflow. |
| [`t1d-excluded-ehr/`](t1d-excluded-ehr/) | Excludes recorded T1D and T2D at the prediction date, plus specified pre-index glycemic evidence | Two saved EHR models with 5- and 10-group options. |

A future module for a T1D-excluded model with diabetes-related screening labs
may be added as a separate folder. It is not included in this release.

## Shared expectations

These packages are for research and independent external validation only. They
are not medical devices and must not be used for individual clinical decisions.
Patient-level input files, derived tables, and predictions remain at the
external site. Sites should return only disclosure-reviewed aggregate results,
figures, and manifests described by the selected package.

Each package has its own verification script, checksum manifest, requirements,
model files, definitions, examples, and instructions. The repository root is
intentionally limited to this guide and repository-wide housekeeping files.
