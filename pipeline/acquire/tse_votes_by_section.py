"""Acquire the TSE votes by section. Contract: pipeline/README.md. Logic: terrain.acquire."""

from terrain.acquire import run_script

if __name__ == "__main__":
    run_script("tse_votes_by_section")
