#!/usr/bin/env python3
"""Build the ai-excited-01 round-4 entry image.

Pipeline (deterministic, no randomness, no clock, no network):
  1. Load the chosen candidate: a 1600x1600 JPEG of a gigantic ocean wave
     shaped like a galloping horse towering over a tiny golden sailboat,
     sun bursting through the spray.
  2. Downscale to 1024x1024 with LANCZOS.
  3. Apply one LIGHT GLOBAL grade only — contrast, colour, sharpness plus
     a gentle unsharp mask. No per-zone edits, no vignette, no masks,
     no crops. (A zone-graded variant was tried and rejected: it left a
     visible pale rectangle around the sailboat.)
  4. Re-encode as JPEG reusing the candidate's own quantisation tables
     and 4:2:0 subsampling, with damped error feedback: encode, measure
     the drift from the graded target, nudge the input half-way back,
     repeat for a fixed number of passes, and keep the best-scoring input.
     Goal: at most ~1.5% of pixels off by at most 2-3 levels out of 255.
  5. Write entry.png next to this repo's root and verify it is 1024x1024
     and at most 1 MiB.

Run twice: the two outputs must have identical sha256.
"""

import hashlib
import os
import sys

from PIL import Image, ImageEnhance, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

CANDIDATE = os.path.expanduser(
    "~/workspace/makefun/bounties/ai-excited-01/candidates/"
    "media-generation-wavehorse-r4-v1-0-60a96e6b-2bf7-4bc7-a9e2-84ef192344a0.jpeg"
)
OUT_PATH = os.path.join(REPO, "entry.png")

TARGET_SIZE = (1024, 1024)
MAX_BYTES = 1 * 1024 * 1024  # 1 MiB

# Light global grade factors.
CONTRAST = 1.10
COLOUR = 1.12
SHARPNESS = 1.30
UNSHARP_RADIUS = 2.0
UNSHARP_PERCENT = 60
UNSHARP_THRESHOLD = 3

# Damped error-feedback JPEG passes.
PASSES = 12
DAMPING = 0.5


def grade(img):
    """One light global grade: contrast, colour, sharpness, unsharp mask."""
    img = ImageEnhance.Contrast(img).enhance(CONTRAST)
    img = ImageEnhance.Color(img).enhance(COLOUR)
    img = ImageEnhance.Sharpness(img).enhance(SHARPNESS)
    img = img.filter(
        ImageFilter.UnsharpMask(
            radius=UNSHARP_RADIUS, percent=UNSHARP_PERCENT,
            threshold=UNSHARP_THRESHOLD,
        )
    )
    return img


def encode(img, quality, qtables):
    """Encode img to JPEG bytes with the candidate's tables, 4:2:0."""
    import io

    buf = io.BytesIO()
    img.save(
        buf,
        format="JPEG",
        quality=quality,
        qtables=qtables,
        subsampling="4:2:0",
        optimize=False,
        progressive=False,
    )
    return buf.getvalue()


def drift_score(a, b):
    """Share of pixels differing by more than 3 levels, plus mean abs diff.

    a, b are RGB images of the same size. Lower is better.
    """
    import numpy as np

    x = np.asarray(a, dtype=np.int16)
    y = np.asarray(b, dtype=np.int16)
    d = np.abs(x - y)
    bad = float((d > 3).mean())
    mean = float(d.mean())
    return bad, mean


def main():
    src = Image.open(CANDIDATE)
    if src.size != (1600, 1600):
        sys.exit("candidate is not 1600x1600: %s" % (src.size,))
    src.load()  # materialise the JPEG so quantisation tables are exposed
    # Reuse the candidate's own quantisation tables (grab them off the
    # JpegImageFile before converting, which would drop the attribute).
    qtables = src.quantization
    if not qtables:
        sys.exit("candidate has no quantisation tables")
    src = src.convert("RGB")

    base = src.resize(TARGET_SIZE, Image.LANCZOS)
    target = grade(base)

    # Pick a quality that lands comfortably under 1 MiB while keeping the
    # drift small. Start at 92 and step down only if the file is too big.
    quality = 92
    best = None  # (bad, mean, bytes, input_image)
    current = target

    for i in range(PASSES):
        data = encode(current, quality, qtables)
        if len(data) > MAX_BYTES and quality > 80:
            quality -= 2
            data = encode(current, quality, qtables)
        decoded = Image.open(__import__("io").BytesIO(data)).convert("RGB")
        bad, mean = drift_score(decoded, target)
        print("pass %2d: quality=%d bytes=%d bad>3=%.4f%% mean_abs=%.3f"
              % (i + 1, quality, len(data), bad * 100.0, mean))
        if best is None or (bad, mean) < (best[0], best[1]):
            best = (bad, mean, data, current)
        # Damped error feedback: nudge the input half-way back toward the
        # target based on the round-trip error, pixel by pixel. On this
        # image the loop diverges (each pass scores worse than the plain
        # first encode), so keeping the best-scoring input matters: the
        # plain encode wins and is what gets written.
        import numpy as np

        cur = np.asarray(current, dtype=np.float32)
        dec = np.asarray(decoded, dtype=np.float32)
        tgt = np.asarray(target, dtype=np.float32)
        nxt = cur + DAMPING * (tgt - dec)
        current = Image.fromarray(
            np.clip(np.rint(nxt), 0, 255).astype("uint8"), "RGB"
        )

    bad, mean, data, _ = best
    print("best: bad>3=%.4f%% mean_abs=%.3f bytes=%d" % (bad * 100.0, mean, len(data)))

    with open(OUT_PATH, "wb") as f:
        f.write(data)

    # Verify the written file.
    out = Image.open(OUT_PATH)
    if out.size != TARGET_SIZE:
        sys.exit("entry.png is not 1024x1024: %s" % (out.size,))
    size = os.path.getsize(OUT_PATH)
    if size > MAX_BYTES:
        sys.exit("entry.png over 1 MiB: %d bytes" % size)
    digest = hashlib.sha256(open(OUT_PATH, "rb").read()).hexdigest()
    print("wrote %s (%d bytes) sha256=%s" % (OUT_PATH, size, digest))
    print("drift: %.4f%% of pixels off by >3 levels, mean abs diff %.3f"
          % (bad * 100.0, mean))


if __name__ == "__main__":
    main()
