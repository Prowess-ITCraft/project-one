# Phase 4: Dataset engine and library

Window: 12 to 20 Oct 2026 (planned). Status: built.

## Goal

Turn the files ITCraft already has (old BOQs, past PrismSuite reports) into datasets the
system can clean, explore and learn from, without anyone building a pipeline by hand.

## Features added

- **Library inbox.** Drop old BOQ PDFs or spreadsheets and PrismSuite reports into the
  library. Each file is hashed, so the same file is never processed twice. The system picks
  the right parser, reads it, and adds the rows to a collection.
- **BOQ parser** for PDF and XLSX quotations. Every row gets a confidence score. Low
  confidence rows are held for a person to fix instead of being trusted.
- **Audit facts.** Each imported PrismSuite report is flattened into one row of facts
  (scores, asset counts, findings) so audits can be compared across customers.
- **Datasets and versions.** Data is stored as Parquet in MinIO. Every change creates a new
  version. A version can never be edited afterwards (a database trigger enforces it).
- **Pipeline steps.** Cleaning and shaping use a fixed list of steps (rename, filter, cast,
  deduplicate, fill, group and so on) run with DuckDB. Clients send step names and options,
  never SQL.
- **Exploration.** Profile a dataset (types, missing values, distinct counts, ranges), draw
  charts, and preview rows.
- **Quarantine and promotion.** Rows that fail checks go to quarantine. A reviewer promotes
  a dataset to "master" with a review step, and the reviewer cannot be the one who made it.
- **History advice.** The BOQ editor can ask "what do past BOQs say about this item"
  (`boq_history`). It returns how often the item appeared, typical quantity and median price.
  It never sets a price.

## Document corpus (added 3 Oct 2026, ADR 0014)

Every library file is converted once into a compact canonical JSON record (text, structure,
cleaned and labelled lines, quality score), stored gzipped and indexed. The collections, the
analysis and training snapshots read the record, not the heavy original. See the
[data guide](../guides/06-data-guide.md). Endpoints: `/library/corpus`, `/library/analysis`,
`/library/rebuild`. The `inbox/` folder is now watched every 5 minutes.

## How it works, in short

1. A file arrives in the library.
2. The importer for its kind reads it and writes rows.
3. Rows are validated and quarantined or accepted.
4. The result is a dataset version you can view, chart, clean, export, or promote.

## Endpoints

`/api/v1/datasets` (list, create, versions, preview, profile, charts, steps, promote,
export) and `/api/v1/library` (upload, status, collections, held rows). See the
[API guide](../guides/04-api-guide.md).

## Who can do what

Analysts and above read datasets. Admin and the Director manage and promote. Field
engineers have no dataset access.

## Known limits

- The BOQ parser reads the ITCraft quotation layout and close relatives. New layouts need a
  parser version.
- Very large files (over 50 MB) are refused.
- The **Library** page in the web app lets you drop files, see what was read and retry failures. Dataset preview, charts and held-row curation screens are planned for phase 12. The API is complete.

## Demo script

1. Upload `samples/` BOQ PDFs through `POST /api/v1/library`.
2. Watch the status reach `done`, then open the collection and see the rows.
3. Ask for history on "Sophos XGS" and see the typical quantity and median price.
