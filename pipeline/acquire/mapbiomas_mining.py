"""Acquire MapBiomas mining shares by type and substance. Contract: pipeline/README.md.

Logic: terrain.earthengine.
"""

from terrain.earthengine import run_script

if __name__ == "__main__":
    run_script("mapbiomas_mining")
