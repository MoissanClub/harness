#!/usr/bin/env python3
"""Split prompt time into vision encoder vs LLM prefill from a `-lv 4 --log-timestamps` server log.

Usage: bench/vit_split.py SERVER_LOG. The encoder runs between the 'encoding mtmd batch' and
'decoding image batch' lines; the rest of 'prompt eval time' is LLM-side work.
"""

import collections
import re
import statistics
import sys


def stamp(line):
    minutes, seconds, millis, micros = map(int, re.match(r"(\d+)\.(\d+)\.(\d+)\.(\d+)", line).groups())
    return minutes * 60000 + seconds * 1000 + millis + micros / 1000


def main():
    groups, start, encoder, image_tokens = collections.defaultdict(list), None, None, None
    for line in open(sys.argv[1]):
        if "encoding mtmd batch" in line:
            start = stamp(line)
        elif "decoding image batch" in line and start is not None:
            encoder = stamp(line) - start
            image_tokens = int(re.search(r"n_tokens_batch = (\d+)", line).group(1))
        elif "prompt eval time" in line and encoder is not None:
            match = re.search(r"prompt eval time =\s+([\d.]+) ms /\s+(\d+) tokens", line)
            groups[image_tokens].append((encoder, float(match.group(1)), int(match.group(2))))
            start = encoder = None
    for image_tokens, rows in sorted(groups.items()):
        rows = rows[2:]  # warm-ups
        vit, prompt, fresh = (statistics.median(row[index] for row in rows) for index in range(3))
        print(f"{image_tokens:4d} image tokens, n={len(rows)}: vision encoder {vit:.1f} ms, prompt_ms {prompt:.1f} "
              f"for {fresh:.0f} fresh tokens, LLM side {prompt - vit:.1f} ms")


if __name__ == "__main__":
    main()
