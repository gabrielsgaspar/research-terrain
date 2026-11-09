"""Acquire IBAMA embargoes. Contract: pipeline/README.md. Logic: terrain.ibama."""

from terrain.ibama import run

if __name__ == "__main__":
    run("ibama_embargos")
