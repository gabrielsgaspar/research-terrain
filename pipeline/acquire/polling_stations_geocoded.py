"""Acquire the geocoded polling stations. Contract: pipeline/README.md. Logic: terrain.acquire."""

from terrain.acquire import run_script

if __name__ == "__main__":
    run_script("polling_stations_geocoded")
