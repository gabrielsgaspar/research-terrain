"""Acquire the TSE general-election party votes. Contract: pipeline/README.md."""

from terrain.acquire import run_script

if __name__ == "__main__":
    run_script("tse_general_parties")
