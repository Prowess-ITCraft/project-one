# Library inbox

Drop old BOQs (PDF, Excel) and PrismSuite reports (Word, JSON) here. The worker checks this
folder every 5 minutes, converts each file once into the document corpus (ADR 0014) and moves it
to `processed/`, `duplicates/` or `failed/`. Files here are never committed.
