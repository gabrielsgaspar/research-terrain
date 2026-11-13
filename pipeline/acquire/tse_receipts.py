"""Acquire TSE campaign receipts by donor sector. Contract: pipeline/README.md."""

from terrain.basedosdados import run

if __name__ == "__main__":
    run("tse_receipts")
