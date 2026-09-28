# Output handling

Keep all source inputs, derived patient tables, and individual predictions
behind the external site's firewall in `LOCAL_ONLY_DO_NOT_RETURN`.

After local disclosure review, return only:

- aggregate results and figures under `RETURN_TO_COORDINATING_CENTER/summary_results/`;
- `run_manifest.json` and the aggregate input audit;
- the Mode B construction attestation, when applicable; and
- a description of material protocol deviations.

Suppress or coarsen small cells according to local policy. Do not return
patient-level predictions or identifiers.
