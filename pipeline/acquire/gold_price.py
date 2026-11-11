"""Acquire the gold price and US CPI. Contract: pipeline/README.md. Logic: terrain.acquire."""

from terrain.acquire import run_script

if __name__ == "__main__":
    run_script("gold_price")
