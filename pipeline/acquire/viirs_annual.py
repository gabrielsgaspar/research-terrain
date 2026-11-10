"""Acquire VIIRS annual night lights. Contract: pipeline/README.md. Logic: terrain.earthengine."""

from terrain.earthengine import run_script

if __name__ == "__main__":
    run_script("viirs_annual")
