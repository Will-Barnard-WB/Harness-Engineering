# Anomaly Patterns — What to Flag

For every receipt, check each pattern below. Assign severity: `ok`, `warning`, or `error`.

## Errors (must be resolved before filing)

- **Missing VAT number**: Receipt has a VAT amount but no VAT number shown
- **Invalid VAT number format**: Does not match GB + 9 digits
- **VAT arithmetic mismatch**: The stated VAT amount does not match the rate × net
  - Allow a rounding tolerance of ±£0.02 per line item
- **VAT charged on exempt supply**: e.g. VAT added to an insurance premium or health service

## Warnings (flag for accountant to review)

- **Reclaim risk items**: Food, alcohol, entertainment, personal items (see vat-rules.md)
- **Round-number VAT**: VAT amount is a suspiciously round number (e.g. £10.00, £20.00)
  that doesn't result naturally from the arithmetic — may have been estimated
- **Zero-rated item charged at standard rate**: e.g. VAT at 20% on a book or food item
- **No receipt date**: Cannot confirm the correct VAT period
- **Supplier name unclear**: Makes ledger matching difficult

## OK (record but no action needed)

- Mixed-rate receipt handled correctly
- VAT number present and valid format
- All arithmetic checks out