# Data guide: the library, the corpus and training data

For anyone adding old BOQs and PrismSuite reports, or preparing data for the learning phase.
Decision record: ADR 0014. Rules: `RULES.md` section 2.

## 1. Why a corpus

PDF and Word files are heavy (the Shakti audit is 1.4 MB) and slow to read. Project One reads
each file **once** and keeps a compact canonical JSON record of it. Everything else, the BOQ
history hints, the analysis and the future models, works from that record.

| Sample | Original | Corpus record (gzip) |
| --- | --- | --- |
| Summary BOQ (PDF) | 85.6 KB | 1.1 KB |
| Priced quotation (PDF) | 151.9 KB | 3.6 KB |
| PrismSuite audit (Word) | 1.38 MB | 17.3 KB |

## 2. How to add files

- **Web app:** Library, drop the files.
- **Folder:** copy files into `inbox/` beside the compose files. The worker checks every
  5 minutes and moves each file to `processed/`, `duplicates/` or `failed/`.
- **Laptop, no server:** `python -m app.cli corpus convert <folder> --out <dir>` writes the
  same JSON records, useful to check a batch before loading it.

The same file is never added twice (it is recognised by its SHA-256 hash).

## 3. What happens to a file

1. **Extract:** text per page (PDF), per document (Word), per sheet (Excel).
2. **Parse:** the BOQ reader or the PrismSuite reader turns text into lines or facts, each with
   a confidence.
3. **Clean** (`CLEANING_VERSION` 1):
   - Unicode, quotes, bullets and spaces normalised;
   - a heading printed over a line at a page break is taken out again
     ("FHoigrhti nPerito /r iStoyphos" becomes "Fortinet / Sophos");
   - common misspellings fixed ("Phoneix" to "Phoenix", "quarentine" to "quarantine");
   - a comparable name (`canonical`) and a grouping key (`name_key`) per line.
4. **Label:** each line gets a gap type (the same keys the BOQ templates use, such as
   `conflicting_av`, `unmanaged_switch`, `firewall_underconfigured`) and a role (product, setup,
   support, service), with the rule that decided it. A setup line with no product name belongs to
   the product line above it.
5. **Validate and score:** completeness, validity, consistency (amount equals quantity times
   price), uniqueness, confidence and labelling give a quality score from 0 to 100, with the
   reasons.
6. **Store:** the gzipped record, an index row, rows in the historical BOQ or audit collection.
   Rows below 0.8 confidence wait in the review queue. A repaired line always waits, with the
   repaired text filled in, so a person only confirms it.

## 4. Reading the analysis

`GET /api/v1/library/analysis` (and the Library page) shows:

- corpus size and how much space conversion saved;
- documents below quality 70 and why;
- lines per gap type, and the share still labelled `other` (needs a better rule or a person);
- per gap type and role: lines, customers, quotes, typical quantity, price quartiles;
- price outliers by median absolute deviation (modified z-score above 3.5, at least 5 prices).
  Outliers are flagged, never removed.

## 5. Training snapshots

Models train only on **frozen** dataset versions (`POST /datasets/{id}/freeze`). The data card
records rows, columns, date range, label and role distributions, cleaning versions, the source
and known issues. Live tables are never used for training.

## 6. When parsers or cleaning improve

Bump `CLEANING_VERSION`, update the golden files (`cli corpus convert ../samples --out
../samples/corpus`), then run `cli corpus rebuild`. Every kept original is read again and each
collection gets a new version; older versions stay readable.

## 7. Keeping or removing originals

By default originals are kept forever, because a better parser may read them again later. An
operator can set `P1_CORPUS_ORIGINALS_RETENTION_DAYS` to remove originals older than N days;
each is removed only after its JSON record is read back and its checksum matches. This cannot be
undone.
