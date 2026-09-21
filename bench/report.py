#!/usr/bin/env python3
"""Print Markdown tables from saved sweeps: bench/report.py experiments/*-latency-TAG ... (stdlib only)."""

import json
from pathlib import Path
import sys


def main():
    print("| Sweep | Variant | Strict | 95% CI | L / C / R | Total p50 / p90 / max ms | Fresh+cached prompt tok | "
          "Prompt ms | Out tok | Decode ms |")
    print("| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for directory in map(Path, sys.argv[1:]):
        tag = directory.name.split("-latency-", 1)[-1]
        for row in json.loads((directory / "summary.json").read_text()):
            ms, by = row["total_ms"], row["by_class"]
            classes = " / ".join(by[label] for label in ("left", "center", "right"))
            if by.get("none", "0/0") != "0/0":
                classes += f" / none {by['none']}"
            low, high = row["strict_ci95"]
            print(f"| {tag} | `{row['variant']}` | {row['strict']}/{row['n']} ({row['strict_rate']:.0%}) | "
                  f"{low:.0%}–{high:.0%} | {classes} | {ms['p50']:.0f} / {ms['p90']:.0f} / {ms['max']:.0f} | "
                  f"{row['prompt_n']:.0f}+{row['cache_n']:.0f} | {row['prompt_ms']:.0f} | "
                  f"{row['predicted_n']:.0f} | {row['predicted_ms']:.0f} |")


if __name__ == "__main__":
    main()
