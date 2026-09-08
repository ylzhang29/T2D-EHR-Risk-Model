# Output handling

Keep behind the external site's firewall:

- all source inputs and intermediate files;
- `LOCAL_ONLY_DO_NOT_RETURN/external_model_input.parquet`;
- `LOCAL_ONLY_DO_NOT_RETURN/external_patient_scores.parquet`; and
- every other patient-level output.

After local disclosure review, the site may return:

- `RETURN_TO_COORDINATING_CENTER/run_manifest.json`;
- `RETURN_TO_COORDINATING_CENTER/external_model_input_audit.json`;
- `RETURN_TO_COORDINATING_CENTER/summary_results/`;
- the completed feasibility precheck and Mode B attestation, when applicable;
  and
- a description of every approved deviation.

Review subgroup and audit tables for small cells and suppress or coarsen them
according to local policy. Never move patient-level files into the return
directory without separate authorization.
