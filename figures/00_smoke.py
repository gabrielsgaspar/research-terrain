"""figures-run smoke test: a fixed image from no data. Contract: figures/README.md."""

import argparse
from pathlib import Path

from terrain import style


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True, type=Path)
    out = parser.parse_args().out_dir
    plt = style.configure()
    fig, ax = plt.subplots(figsize=(3, 2))
    ax.plot([0, 1, 2], [0, 1000, 0])
    ax.yaxis.set_major_formatter(style.THOUSANDS)
    ax.set_title("figures-run smoke test")
    style.save_png(fig, out / "00_smoke.png")


if __name__ == "__main__":
    main()
