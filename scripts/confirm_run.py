"""Run a registered specification on the confirmation half (terrain.confirm).

Called only by `.github/workflows/confirm-run.yml` (shuffled) and
`.github/workflows/unblind.yml` (real). A real run refuses outside its workflow.

    confirm_run.py check  --spec confirm/specs/X.yaml --mode shuffled|real [--accept-failed-shuffle]
    confirm_run.py run    --spec confirm/specs/X.yaml --mode shuffled|real --out-dir DIR
    confirm_run.py ledger --spec confirm/specs/X.yaml --mode shuffled|real --output DIR/output.json

`check` reads only the repository (no credentials). `run` needs
TERRAIN_BUCKET and the terrain-unblind account. `ledger` writes one new file
into confirm/ledger/ and prints its path.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from terrain import confirm

REPO = Path(__file__).resolve().parents[1]
LEDGER = REPO / "confirm" / "ledger"
SPLIT_HASH = REPO / "confirm" / "split.sha256"


def _label(spec: confirm.Spec, mode: str, accept: bool) -> str:
    entries = confirm.read_ledger(LEDGER)
    if mode == confirm.REAL:
        return confirm.check_unblind(spec, entries, accept_failed_shuffle=accept)
    return confirm.check_shuffled(spec, entries)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["check", "run", "ledger"])
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--mode", choices=confirm.MODES, required=True)
    parser.add_argument("--accept-failed-shuffle", action="store_true")
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    spec = confirm.load_spec(args.spec.read_bytes())
    try:
        label = _label(spec, args.mode, args.accept_failed_shuffle)
        if args.command == "check":
            confirm.check_pap_commit(REPO, spec.pap_commit)
            print(f"{spec.id}: OK for a {args.mode} run, ledger label {label!r}")
            return 0

        if args.command == "run":
            from terrain.storage import GCSStore

            if args.out_dir is None:
                parser.error("run needs --out-dir")
            confirm.check_pap_commit(REPO, spec.pap_commit)
            confirm.load_registered()
            output = confirm.run(
                spec,
                GCSStore(os.environ["TERRAIN_BUCKET"]),
                args.mode,
                SPLIT_HASH.read_text(encoding="utf-8"),
                os.environ,
            )
            print(confirm.write_output(args.out_dir, output))
            return 0

        if args.output is None:
            parser.error("ledger needs --output")
        output = json.loads(args.output.read_text(encoding="utf-8"))
        if output.get("spec_sha256") != spec.sha256:
            raise confirm.ConfirmError("the output is not from this specification")
        entry = confirm.ledger_entry(
            output,
            label,
            run_id=os.environ["GITHUB_RUN_ID"],
            run_url=os.environ["RUN_URL"],
            code_commit=os.environ["CODE_COMMIT"],
            date_utc=dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            accept_failed_shuffle=args.accept_failed_shuffle,
        )
        print(confirm.write_ledger_entry(LEDGER, entry).relative_to(REPO).as_posix())
        return 0
    except confirm.ConfirmError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
