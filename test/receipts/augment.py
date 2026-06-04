"""Scan / phone-photo augmentation for synthetic receipts (Track B realism layer).

Takes a clean rendered receipt image and degrades it the way a real scan or phone
photo would — rotation, slight perspective, sensor noise, blur, uneven lighting, and
JPEG recompression — so the OCR + classifier are tested on realistic, not pristine,
input. Pure PIL + numpy (no opencv). Deterministic given a seed.
"""

from __future__ import annotations

import io
import random

import numpy as np
from PIL import Image, ImageFilter


def _find_coeffs(target, source):
    """Perspective coefficients mapping the output `target` quad to input `source`."""
    matrix = []
    for (tx, ty), (sx, sy) in zip(target, source):
        matrix.append([sx, sy, 1, 0, 0, 0, -tx * sx, -tx * sy])
        matrix.append([0, 0, 0, sx, sy, 1, -ty * sx, -ty * sy])
    A = np.array(matrix, dtype=float)
    B = np.array(target, dtype=float).reshape(8)
    return np.linalg.solve(A, B)


def _perspective(img: Image.Image, mag: float, rng: random.Random) -> Image.Image:
    w, h = img.size
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    j = lambda v: v * rng.uniform(-mag, mag)  # noqa: E731
    tgt = [
        (j(w), j(h)),
        (w + j(w), j(h)),
        (w + j(w), h + j(h)),
        (j(w), h + j(h)),
    ]
    coeffs = _find_coeffs(tgt, src)
    return img.transform((w, h), Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor="white")


def _add_noise(img: Image.Image, sigma: float) -> Image.Image:
    arr = np.asarray(img).astype(np.float32)
    arr += np.random.normal(0, sigma, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _lighting(img: Image.Image, strength: float, rng: random.Random) -> Image.Image:
    arr = np.asarray(img).astype(np.float32)
    h, w = arr.shape[:2]
    cx, cy = rng.uniform(0, w), rng.uniform(0, h)
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / np.sqrt(w**2 + h**2)
    grad = (0.5 - dist) * strength * 255
    if arr.ndim == 3:
        grad = grad[..., None]
    return Image.fromarray(np.clip(arr + grad, 0, 255).astype(np.uint8))


def scan_augment(img: Image.Image, *, seed: int | None = None, intensity: str = "medium") -> Image.Image:
    """Return a degraded copy of `img` simulating a scan/photo. `intensity` ∈
    light|medium|heavy controls how aggressive the degradation is."""

    rng = random.Random(seed)
    img = img.convert("RGB")
    cfg = {
        "light": dict(rot=1.2, persp=0.01, blur=(0.2, 0.6), noise=(3, 7), light=0.10, jpeg=(75, 90)),
        "medium": dict(rot=2.5, persp=0.025, blur=(0.4, 1.1), noise=(5, 13), light=0.18, jpeg=(55, 80)),
        "heavy": dict(rot=4.0, persp=0.05, blur=(0.8, 1.8), noise=(10, 22), light=0.28, jpeg=(38, 62)),
    }[intensity]

    img = img.rotate(rng.uniform(-cfg["rot"], cfg["rot"]), expand=True, fillcolor="white")
    if rng.random() < 0.7:
        img = _perspective(img, cfg["persp"], rng)
    if rng.random() < 0.7:
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(*cfg["blur"])))
    img = _add_noise(img, rng.uniform(*cfg["noise"]))
    img = _lighting(img, rng.uniform(cfg["light"] * 0.6, cfg["light"]), rng)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=rng.randint(*cfg["jpeg"]))
    buf.seek(0)
    return Image.open(buf).convert("RGB")
