# Data

No real data lives in git. Everything is in Google Cloud Storage:

```
gs://research-terrain/data/
  raw/       downloads exactly as received; write-once (the acquire account
             can create objects but not overwrite or delete them)
  derived/   cleaned panels (Parquet, GeoParquet), rebuilt by the pipeline
  explore/   exploration outputs; deleted automatically after 90 days
gs://research-terrain-sealed/
             the full sample split; readable only by the unblind account
```

- `catalog.yaml` lists every dataset, its source and its GCS path.
- `contracts/` holds the schema each derived table must satisfy.
- `fixtures/` holds small text samples (CSV or JSON, under 200 KB) cut from
  real data, for tests. Tests never read GCS.

Query Parquet in place with DuckDB rather than downloading whole files.
