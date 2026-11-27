"""Synthetic checks of the angle tracker and the seven-segment reader.

    python3 tools/auto_rig/tests/test_vision.py
"""
import math
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auto_rig.vision import AngleTracker, SevenSegReader, SEGMENTS, ARUCO_DICT  # noqa: E402

PX_PER_MM = 12.0


def marker_img(mid, size_mm):
    d = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    n = int(size_mm * PX_PER_MM)
    m = cv2.aruco.generateImageMarker(d, mid, n)
    return cv2.copyMakeBorder(m, n // 6, n // 6, n // 6, n // 6, cv2.BORDER_CONSTANT, value=255)


def paste_rotated(canvas, img, centre, deg, squash=1.0):
    h, w = img.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    if squash != 1.0:  # out-of-plane tilt: shrink across the marker before rotating
        S = np.array([[1, 0, 0], [0, squash, h * (1 - squash) / 2], [0, 0, 1]])
        M = M @ S
    M[:, 2] += np.array(centre) - np.array([w / 2, h / 2])
    warped = cv2.warpAffine(img, M, canvas.shape[::-1], borderValue=255, flags=cv2.INTER_LINEAR)
    mask = cv2.warpAffine(np.full_like(img, 255), M, canvas.shape[::-1], borderValue=0)
    canvas[mask > 0] = warped[mask > 0]


def scene(joint_deg, squash=1.0, skew=True):
    c = np.full((900, 1200), 200, np.uint8)
    paste_rotated(c, marker_img(0, 16), (300, 450), 0.0)
    paste_rotated(c, marker_img(1, 14), (800, 450), -joint_deg, squash)
    if skew:  # camera off square: a perspective warp of the whole view
        src = np.float32([[0, 0], [1200, 0], [1200, 900], [0, 900]])
        dst = np.float32([[60, 30], [1150, 0], [1200, 900], [0, 860]])
        c = cv2.warpPerspective(c, cv2.getPerspectiveTransform(src, dst), (1200, 900), borderValue=200)
    return cv2.cvtColor(c, cv2.COLOR_GRAY2BGR)


def test_angle():
    tr = AngleTracker(fixed_size_mm=16, moving_size_mm=14)
    r0 = tr.measure(scene(0.0))
    tr.set_zero(r0.raw_deg)
    sgn = None
    worst = 0.0
    for a in (5, 15, 30, 45, 60, 75, 90):
        r = tr.measure(scene(a))
        assert r.angle_deg is not None, f"markers lost at {a}"
        sgn = sgn or (1 if r.angle_deg > 0 else -1)
        err = abs(sgn * r.angle_deg - a)
        worst = max(worst, err)
    assert worst < 0.5, worst
    r = tr.measure(scene(30, squash=math.cos(math.radians(20))))
    assert abs(r.twist_deg - 20) < 3, r.twist_deg
    print(f"angle: worst error {worst:.2f} deg over 5-90 deg with a skewed camera; "
          f"20 deg twist read as {r.twist_deg:.1f} deg")


def draw_digits(text, dark=True, slant=0.0):
    cw, H = 60, 100
    img = np.full((H, cw * len(text)), 230 if dark else 20, np.uint8)
    on_col = 30 if dark else 240
    segs = {"0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg", "5": "acdfg",
            "6": "acdefg", "7": "abc", "8": "abcdefg", "9": "abcdfg", "-": "g", " ": ""}
    full = {"a": (0.2, 0.0, 0.8, 0.13), "b": (0.72, 0.08, 0.92, 0.48), "c": (0.72, 0.52, 0.92, 0.92),
            "d": (0.2, 0.87, 0.8, 1.0), "e": (0.08, 0.52, 0.28, 0.92), "f": (0.08, 0.08, 0.28, 0.48),
            "g": (0.2, 0.44, 0.8, 0.56)}
    for i, ch in enumerate(text):
        x0 = i * cw + 0.06 * cw
        w = cw * 0.88
        for s in segs[ch]:
            a, b, c, d = full[s]
            cv2.rectangle(img, (int(x0 + a * w), int(b * H)), (int(x0 + c * w), int(d * H)), on_col, -1)
    pad = cv2.copyMakeBorder(img, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=230 if dark else 20)
    return cv2.cvtColor(pad, cv2.COLOR_GRAY2BGR)


def test_sevenseg():
    for text, dec, want in (("1234", 0, 1234), (" 482", 1, 48.2), ("  57", 0, 57), ("2005", 2, 20.05)):
        img = draw_digits(text)
        h, w = img.shape[:2]
        r = SevenSegReader(corners=[[40, 40], [w - 40, 40], [w - 40, h - 40], [40, h - 40]],
                           n_digits=len(text), decimals=dec, gap=0.12, stable_frames=1)
        v, txt = r.read(img)
        assert v is not None and abs(v - want) < 1e-9, (text, v, txt)
    print("seven-segment: 4 test displays decoded correctly")


if __name__ == "__main__":
    test_angle()
    test_sevenseg()
    print("vision tests passed")
