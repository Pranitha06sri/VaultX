# Synthetic receipts only

These PDFs are fictional fixtures for FDR Intelligence. They contain no actual bank receipts, real account information, funds, or verification results. Each page is visibly marked **SYNTHETIC SAMPLE — NOT A BANK DOCUMENT**.

| File | Intended scenario |
| --- | --- |
| `valid-fdr.pdf` | Complete fields; maturity 15 days after generation. |
| `missing-fields.pdf` | Unreadable holder and maturity date. |
| `duplicate-fdr.pdf` | Same instrument number as `valid-fdr.pdf`. |
| `below-minimum.pdf` | 500.00 INR, below the default 10,000 INR threshold. |
| `invalid-dates.pdf` | Maturity before issue. |

Upload `valid-fdr.pdf` alone to try approval without exceptions. Upload `duplicate-fdr.pdf` next to exercise the duplicate rule. The dashboard's **Load sample workspace** button loads all five, so the standard receipt will intentionally have a duplicate finding.

Regenerate with current dates from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts/generate-samples.py
```

The API also generates fresh fixtures through `GET /samples/{name}`. The seed endpoint is idempotent and preserves existing reviews. It does not refresh already seeded maturity dates.
