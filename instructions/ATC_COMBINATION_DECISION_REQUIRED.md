# ATC combination-product decision — required before distribution

The training data came from EHR medication-ingredient tables. Combination
products were represented through their component ingredient RxCUIs. The
supplied primary ATC lookup therefore contains exact fifth-level,
single-ingredient codes corresponding to that ingredient-level definition. It
does not currently include combination-product ATC codes.

This is a prerequisite feasibility question before the site extracts outcomes:

> Does the site's ATC medication source represent a combination product through
> each active ingredient (so both single-ingredient and combination products
> contribute ingredient-level records), or only through a combination-product
> ATC code?

Before external validation, determine how the external medication source stores
combination products:

- If the source expands products into ingredient-level ATC records, retain the
  current lookup and document that behavior.
- If the source stores only combination-product ATC codes, it should decompose
  each product into component ingredients before applying the locked lookup.
  If decomposition is unavailable, the current lookup will undercount diuretic
  and statin records. The coordinating investigators must then approve an
  explicit combination-code crosswalk or a prespecified sensitivity analysis
  before outcomes are examined.

The site should report, before scoring:

1. Number of medication rows with a valid fifth-level ATC code.
2. Number and percentage matching the locked lookup.
3. Frequencies of unmatched C03 and C10 codes.
4. Whether combination products are expanded to ingredients upstream.
5. If they are not expanded, whether the site can supply or implement a frozen
   ingredient decomposition before outcomes are examined.

Do not add codes after examining external model performance.
