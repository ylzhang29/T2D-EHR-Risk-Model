# Output handling and return instructions

The pipeline creates two visibly separated directories.

## `LOCAL_ONLY_DO_NOT_RETURN`

These files remain behind the external site's firewall:

- `external_model_input.parquet`: patient-level constructed predictors,
  outcome, follow-up, and subgroup fields.
- `external_patient_scores.parquet`: patient-level raw and calibrated risks.
- `.matplotlib/`: local software cache.
- All original input and intermediate source files.

Do not email, upload, or return these files without separate data-transfer and
privacy authorization.

## `RETURN_TO_COORDINATING_CENTER`

Return this directory only after the site privacy officer or designated analyst
confirms that its contents satisfy local disclosure rules:

- `run_manifest.json`: input filenames and hashes, seed, software versions,
  calibration provenance, thresholds, and subgroup plan; no patient records.
- `external_model_input_audit.json`: aggregate cohort construction, exclusions,
  mapping coverage, age summaries, and medication matching diagnostics.
- `summary_results/`: aggregate metrics, bootstrap results, calibration, ROC/PR
  curve coordinates, subgroup summaries when estimable, DCA/CIC tables, and
  figures.
- Completed `SITE_FEASIBILITY_PRECHECK.md` and a written description of every
  approved deviation.

Before return, inspect small cells in subgroup and audit tables. Suppress or
coarsen them according to the site's disclosure policy; document any change.
Never move patient-level files into the return directory.
