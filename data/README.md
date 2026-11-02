# Data

No real data lives in git. Everything is in one bucket, `gs://research-terrain/`:

```
data/
  raw/<source>/<YYYY-MM-DD>/     downloads exactly as received, plus a
                                 _MANIFEST.json; write-once (nobody but the
                                 owner can overwrite or delete)
  derived/<dataset>/<hash>/      cleaned panels (Parquet, GeoParquet); the hash
                                 covers inputs and code, so nothing is rebuilt
                                 or overwritten
  derived/split/                 the exploration municipality list
  explore/<idea>/                exploration outputs; deleted after 90 days
sealed/split/                    the full split; readable only by the unblind
                                 account
```

Who can do what (IAM conditions, set by `scripts/gcp/setup_gcs.sh`):

| Account | Reads | Writes |
| --- | --- | --- |
| terrain-acquire | data/raw/ | create in data/raw/ |
| terrain-build | data/raw/, data/derived/ | create in data/derived/ |
| terrain-analysis | data/derived/, data/explore/ | data/explore/ |
| terrain-unblind | data/derived/, sealed/ | nothing |

Agents never hold these credentials. They write code and test it on
`fixtures/`; the code runs against GCS only after it is merged, in a workflow
bound to a GitHub environment.

## Never twice

1. `catalog.yaml` says what each dataset is and where it comes from;
   `manifests/<stage>/<name>.json` says what has actually reached GCS. The
   `data-pipeline` workflow opens a PR adding the manifest after every run, so
   the planner sees new data once you merge it.
2. Every raw folder has a `_MANIFEST.json`: source URL, retrieval time,
   SHA-256 and size per file, and the commit of the script that fetched it.
   Acquire scripts skip a source whose target path already has one.
3. Derived paths include a hash of the input manifests and the build code, so
   an unchanged build finds its output and stops.

- `contracts/` holds the schema each derived table must satisfy.
- `fixtures/` holds small text samples (CSV or JSON, under 200 KB) cut from
  real data, for tests. Tests never read GCS.

Query Parquet in place with DuckDB rather than downloading whole files.
