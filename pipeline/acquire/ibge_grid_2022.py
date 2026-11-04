"""Acquire the IBGE 2022 census grid. Contract: pipeline/README.md. Logic: terrain.acquire."""

from terrain.acquire import run_script

if __name__ == "__main__":
    run_script("ibge_grid_2022")
