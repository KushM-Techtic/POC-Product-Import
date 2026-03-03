# Data Enrichment → BigCommerce POC – Scope Document

## Overview

**Core question to prove:** Can we take a client file, scrape a brand site, and produce a BigCommerce-ready Excel with enriched data and images?

**Scope:** One brand, one format, one output.  
**Effort:** 20 hours.  
**Success:** Upload Tuffy Security's file → get a BigCommerce-ready Excel with scraped descriptions and images for **≥80% of products matched**, with manual effort near zero.

---

## Source Data

All client-provided files for this POC are in the **`source data/`** folder:

| File | Description |
|------|--------------|
| **Tuffy Security_HS_Export_02-23-2026.xlsx** | BigCommerce export – **target format**. Defines column names and structure for the output Excel. |
| **Tuffy Security_BHRQ_02-23-2026.xlsx** | DCI source data – **input to enrich**. Product data; some fields may be missing. |
| **Tuffy Security Products - 15% off Retail-MAP.xlsx** | Brand rep data – pricing/MAP, part numbers, UPCs; use for reference/matching. |
| **Attached Message Part.html** | Client email attachment (message body). |
| **attachment.png** | Client email attachment (image). |

---

## Phase Breakdown (20 hours)

| Phase | Hours | What to do |
|-------|--------|------------|
| **1 – Input handling** | 3 | Excel/CSV only. **Hardcoded** column mapping for Tuffy. **Flag missing fields** per row. |
| **2 – Brand / website** | 1 | **Hardcoded** brand name + URLs in a config file. No discovery logic. |
| **3 – Scraping + images** | 6 | Scrape product listing → product pages. Extract **title, description, images** only (no specs/price). Download + **resize images** to BigCommerce spec. Basic retry/skip on failure. |
| **4 – Matching + enrichment** | 5 | Match by **SKU/name** first; if no match, **one simple LLM call** for fuzzy match. Fill **missing description only** from scraped text. Attach images to matched rows. |
| **5 – Excel export** | 3 | **Hardcoded** BigCommerce column mapping. One `.xlsx` with image paths/URLs. **Flag still-missing rows.** |
| **Integration + E2E testing** | 2 | Run full pipeline; validate output. |
| **Total** | **20** | |

---

## What Stays (Essential for POC)

- **Phase 1:** Excel/CSV only. Hardcoded column mapping for the one test brand. Flag missing fields per row.
- **Phase 2:** Hardcode brand name + URLs in a config file. No discovery logic.
- **Phase 3:** Scrape listing → product pages. Extract title, description, images only. Download + resize images to BigCommerce spec. Basic retry/error handling; skip failures.
- **Phase 4:** SKU/name match first; simple LLM call for fuzzy match. Fill missing **description** only. Attach images to matched rows.
- **Phase 5:** Hardcoded BigCommerce column mapping. One `.xlsx` output with image paths/URLs. Flag still-missing rows.
- **Phase 6:** Skip. Generalization comes after POC validation.

---

## What Gets Cut (Out of Scope for POC)

| Cut | Why |
|-----|-----|
| Auto schema detection | Not needed for one known brand. |
| JSON/XML input | Adds complexity; low POC value. |
| Multi-brand config system | Validate one brand first. |
| AI description normalization | Use raw scraped text; good enough for POC. |
| Logging/reporting dashboard | Manual inspection is fine at POC stage. |
| robots.txt / rate-limit sophistication | Basic sleep/retry is sufficient. |

---

## Success Criteria

- **Input:** Tuffy Security's file (from `source data/`).
- **Output:** BigCommerce-ready Excel with:
  - Scraped descriptions filled where missing.
  - Images downloaded, resized, and referenced (paths or URLs in one location).
- **≥80% of products** matched and enriched.
- **Manual effort** near zero (single run, single file out).

If these are met → greenlight the full build.

---

## BigCommerce Demo Store (for validation)

- **Dashboard URL:** [https://store-oqdqcdc6bu.mybigcommerce.com/manage/dashboard](https://store-oqdqcdc6bu.mybigcommerce.com/manage/dashboard)
- **Email:** ronak@techtic.agency  
- **Password:** *(stored securely; use for POC import validation only)*

Use this store to confirm the exported Excel imports correctly and products show without missing data (or only expected optional gaps).

---

## Folder Structure (after setup)

```
poc/
├── source data/          # Client input files (Tuffy Excel + attachments)
│   ├── Tuffy Security_HS_Export_02-23-2026.xlsx
│   ├── Tuffy Security_BHRQ_02-23-2026.xlsx
│   ├── Tuffy Security Products - 15% off Retail-MAP.xlsx
│   ├── Attached Message Part.html
│   └── attachment.png
└── docs/
    └── POC-Scope.md      # This document
```

---

*Last updated: POC scope as agreed with PM (minimal 20-hour scope).*
