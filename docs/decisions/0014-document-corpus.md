# ADR 0014: Document corpus, convert once to canonical JSON

Status: accepted
Date: 2026-10-03

## Context

Old BOQs and PrismSuite reports arrive as PDF and Word files, and many more will arrive over
time. They are the largest future training set (BOQ line prediction, ranking, price drift).
We don't want the heavy originals weighing down the tool or the deployment. The ask was that every
file be converted to a lighter format such as JSON or XML, and that this data be collected
continuously, cleaned and analysed properly because models will train on it.

The library (Phase 4) already parses files into Parquet rows, but it keeps only rows. The full
text, the parser's view of the document and the quality judgement are thrown away, so a better
parser or a new feature later would need the heavy original again.

## Decision

1. Every library file is converted **once** into a canonical JSON record, schema
   `p1.corpus.v1`, stored gzipped in object storage under `corpus/<sha256>.json.gz` and indexed
   in the `corpus_documents` table. JSON, not XML: it maps one to one to our Pydantic and
   Parquet types, is smaller after gzip, and is what the API and the ML tooling already speak.
2. The record holds: source facts (name, sha256, size, media type, pages), parser name and
   version, cleaning version, plain text per page, the structured document (BOQ document or
   audit snapshot), cleaned and labelled lines, and a quality report.
3. Downstream code (BOQ history, analysis, training snapshots) reads the JSON and the Parquet
   collections, never the original.
4. **Cleaning** is a pure, versioned module (`datasets/cleaning.py`): Unicode and whitespace
   normalisation, removal of interleaved page-header noise, canonical component names, money and
   quantity parsing, exact and near-duplicate detection, and a **taxonomy label** per BOQ line
   (sanitization, endpoint security, managed switch, firewall, server, NAS and backup, DR, DLP,
   RAM, Office, hardening, service, other) that matches the BOQ template gap types.
5. **Quality** per document: completeness, validity, consistency (amount equals qty times price),
   uniqueness and mean parser confidence, combined into a 0 to 100 score. Per collection: label
   distribution, price bands per label (median and quartiles), robust outliers (median absolute
   deviation) on price and quantity, flagged but never removed.
6. **Originals are kept by default.** Purging them is irreversible and the decision belongs to
   Aditya. `P1_CORPUS_ORIGINALS_RETENTION_DAYS` (0 means keep forever) lets an operator purge
   originals older than N days once their JSON checksum is verified.
7. `samples/` is converted with the same code (`cli corpus convert`, no database needed) and the
   result is committed in `samples/corpus/` so tests and new developers see the exact output.
8. Training uses frozen dataset versions with a data card (rows, labels, sources, cleaning
   version, quality summary).

## Consequences

- Heavy files are touched once. The API and analysis work on kilobytes, not megabytes.
- Parser improvements can be re-applied (`cli corpus reparse`) while originals are kept.
- One new table and one migration. The corpus lives in the `datasets` module beside the library.
- If originals are purged, a future parser cannot re-read them; the JSON text is the fallback.
