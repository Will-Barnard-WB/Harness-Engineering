# Output Schema

Every analysis must produce two files in the `ledger/` directory.

## 1. JSON file: `ledger/YYYY-MM-DD_<supplier-slug>.json`

```json
{
  "supplier": "string or null",
  "vat_number": "string or null",
  "receipt_date": "YYYY-MM-DD or null",
  "line_items": [
    {
      "description": "string",
      "net": 0.00,
      "vat_rate": "20%" | "5%" | "0%" | "exempt",
      "vat": 0.00,
      "gross": 0.00,
      "note": "string or null"
    }
  ],
  "totals": {
    "net": 0.00,
    "vat": 0.00,
    "gross": 0.00
  },
  "flags": [
    {
      "severity": "ok" | "warning" | "error",
      "message": "string"
    }
  ],
  "status": "pending_approval"
}
```

## 2. Markdown summary: `ledger/YYYY-MM-DD_<supplier-slug>.md`

Plain English for the accountant to review. Include:
- What the receipt is for
- Total VAT and whether it appears reclaimable
- Any flags that need attention
- A clear recommendation: Approve / Review needed / Do not file

## Supplier slug rules

- Lowercase, hyphens instead of spaces
- Maximum 30 characters
- Remove Ltd, Limited, PLC from the end
- Example: "Henderson Office Supplies Ltd" → `henderson-office-supplies`