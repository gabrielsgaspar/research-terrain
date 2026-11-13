"""Acquire IBGE annual population. Contract: pipeline/README.md. Logic: terrain.basedosdados."""

from terrain.basedosdados import run

if __name__ == "__main__":
    run("ibge_population_annual")
