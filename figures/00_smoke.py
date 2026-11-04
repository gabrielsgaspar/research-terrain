"""figures-run smoke test: a fixed image from no data. Contract: figures/README.md."""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True, type=Path)
    out = parser.parse_args().out_dir
    out.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(3, 2))
    ax.plot([0, 1, 2], [0, 1, 0])
    ax.set_title("figures-run smoke test")
    fig.savefig(out / "00_smoke.png", dpi=100)
    fig.savefig(out / "00_smoke.pdf", metadata={"CreationDate": None})
    plt.close(fig)


if __name__ == "__main__":
    main()
