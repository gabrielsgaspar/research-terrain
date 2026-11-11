"""Acquire the SGB mineral occurrences. Contract: pipeline/README.md. Logic: terrain.acquire."""

from terrain.acquire import run_script

if __name__ == "__main__":
    run_script("sgb_gold_occurrences")
