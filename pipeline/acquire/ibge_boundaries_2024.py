"""Acquire the IBGE 2024 boundaries. Contract: pipeline/README.md. Logic: terrain.acquire."""

from terrain.acquire import run_script

if __name__ == "__main__":
    run_script("ibge_boundaries_2024")
