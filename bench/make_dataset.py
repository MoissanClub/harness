#!/usr/bin/env python3
"""Build a labeled fridge-bearing image set from the three source kitchens (macOS sips).

Sliding 3:2 crops (two zoom levels) of each 1536x1024 source, plus mirrored copies, move the fridge
across the frame at known positions. Labels come from the fridge centre's
horizontal fraction, not from the model: <= LEFT_MAX expects turn_left,
CENTER band expects no turn, >= RIGHT_MIN expects turn_right. Crops in the gaps
between bands are ambiguous for a 30-degree turn quantum and are not generated.
"""

import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "bench/images"
SRC_W, SRC_H = 1536, 1024
OUT_W, OUT_H = 720, 480
# Fridge horizontal extent in source pixels, measured on the 720-wide renders.
SOURCES = {
    "center": ("assets/kitchen-source.png", 292 / 720 * SRC_W, 438 / 720 * SRC_W),
    "left": ("assets/kitchen-left-source.png", 167 / 720 * SRC_W, 285 / 720 * SRC_W),
    "right": ("assets/kitchen-right-source.png", 508 / 720 * SRC_W, 640 / 720 * SRC_W),
}
CROPS = ((1152, 768, 64), (960, 640, 32))  # width, height, top offset keeping the fridge in view
LEFT_MAX, CENTER_MIN, CENTER_MAX, RIGHT_MIN = 0.33, 0.43, 0.57, 0.67
MIN_VISIBLE = 0.85  # fraction of fridge width that must remain inside the crop
# Fridge-free windows (source, x offset, y offset, width, height) for the target-absent check.
ABSENT = [("center", 0, 200, 576, 384), ("center", 960, 200, 576, 384), ("left", 640, 100, 864, 576),
          ("left", 672, 300, 864, 576), ("right", 0, 32, 960, 640), ("right", 96, 200, 960, 640),
          ("right", 0, 300, 1056, 704)]


def label(fraction):
    if fraction <= LEFT_MAX:
        return "turn_left"
    if fraction >= RIGHT_MIN:
        return "turn_right"
    if CENTER_MIN <= fraction <= CENTER_MAX:
        return None
    return "ambiguous"


def sips(*args):
    subprocess.run(["sips", *map(str, args)], check=True, capture_output=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, (source, x0, x1) in SOURCES.items():
        windows = [("full", 0, 0, SRC_W, SRC_H)]
        for crop_w, crop_h, off_y in CROPS:
            for off_x in range(0, SRC_W - crop_w + 1, 48):
                windows.append((f"w{crop_w}x{off_x:03d}", off_x, off_y, crop_w, crop_h))
        for tag, off_x, off_y, width, height in windows:
            visible = (min(x1, off_x + width) - max(x0, off_x)) / (x1 - x0)
            fraction = ((x0 + x1) / 2 - off_x) / width
            if visible < MIN_VISIBLE or label(fraction) == "ambiguous":
                continue
            for mirrored in (False, True):
                frac = 1 - fraction if mirrored else fraction
                path = OUT / f"{name}-{tag}{'-m' if mirrored else ''}.png"
                sips("-c", height, width, "--cropOffset", off_y, off_x, ROOT / source, "--out", path)
                if mirrored:
                    sips("-f", "horizontal", path)
                sips("-z", OUT_H, OUT_W, path)
                entries.append({"image": str(path.relative_to(ROOT)), "source": name, "window": tag,
                                "mirrored": mirrored, "fridge_center_fraction": round(frac, 3),
                                "fridge_visible": round(visible, 2), "expected_turn": label(frac)})
    (ROOT / "bench/dataset.json").write_text(json.dumps(entries, indent=2) + "\n")
    absent = []
    for index, (name, off_x, off_y, width, height) in enumerate(ABSENT):
        for mirrored in (False, True):
            path = OUT / f"absent-{name}-{index}{'-m' if mirrored else ''}.png"
            sips("-c", height, width, "--cropOffset", off_y, off_x, ROOT / SOURCES[name][0], "--out", path)
            if mirrored:
                sips("-f", "horizontal", path)
            sips("-z", OUT_H, OUT_W, path)
            absent.append({"image": str(path.relative_to(ROOT)), "source": name, "mirrored": mirrored})
    (ROOT / "bench/absent.json").write_text(json.dumps(absent, indent=2) + "\n")
    counts = {}
    for entry in entries:
        counts[entry["expected_turn"]] = counts.get(entry["expected_turn"], 0) + 1
    print(f"{len(entries)} images -> {OUT}; labels: {counts}")


if __name__ == "__main__":
    main()
