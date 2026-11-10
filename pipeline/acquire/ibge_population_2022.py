"""Acquire IBGE's census population table. Contract: pipeline/README.md. Logic: terrain.acquire."""

from terrain.acquire import run_script

if __name__ == "__main__":
    run_script("ibge_population_2022")
