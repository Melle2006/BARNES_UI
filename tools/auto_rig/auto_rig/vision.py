"""Camera measurements for the automated rig: joint angle from ArUco markers, force from the scale.

Angle
-----
Two ArUco markers (DICT_4X4_50) are seen by one camera looking square-ish at the side of the rig:

* the FIXED marker (id 0) on the rig post's finger-side face, and
* the MOVING marker (id 1) on the marker flag pinned to the load adapter.

The fixed marker's four corners give a homography from the image to its own plane, in mm. The
moving marker's corners are mapped through it, so its orientation is measured in that plane, not
in the (perspective-distorted) image: the camera does not have to be exactly square on. The flag
sits about 5 mm in front of the post face, which only scales the map slightly and does not bias
the angle. The joint angle is the change of that orientation from the zero recorded with the
finger straight.

Out-of-plane motion (the adapter twisting, or a strip buckling sideways) makes the moving marker
look rectangular instead of square in that plane: ``twist_deg`` = arccos(short side / long side)
is reported with every reading, and the tests use it to flag sideways buckling.

Force (scale display)
---------------------
``SevenSegReader`` reads a seven-segment LCD/LED display: the four corners of the digits are
marked once (``calibrate_scale``), the patch is warped to a rectangle, thresholded, cut into digit
cells, and seven sample windows per cell are tested. A value is only accepted after it repeats in
``stable_frames`` consecutive frames, which rejects the flicker as a digit changes.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

ARUCO_DICT = cv2.aruco.DICT_4X4_50
FIXED_ID, MOVING_ID = 0, 1


# ----------------------------------------------------------------------------- cameras
class Camera:
    """A USB camera (index) or a phone stream (URL, e.g. IP Webcam / DroidCam:
    'http://192.168.1.20:8080/video')."""

    def __init__(self, source, width=None, height=None):
        self.source = int(source) if str(source).isdigit() else source
        self.cap = cv2.VideoCapture(self.source)
        if width:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if height:
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if not self.cap.isOpened():
            raise RuntimeError(f"cannot open camera {source!r}")

    def read(self):
        # drop buffered frames so the reading is current (phone streams buffer several)
        for _ in range(2):
            self.cap.grab()
        ok, frame = self.cap.read()
        if not ok:
            raise RuntimeError("camera read failed")
        return time.time(), frame

    def close(self):
        self.cap.release()


# ----------------------------------------------------------------------------- angle
@dataclass
class AngleReading:
    t: float
    angle_deg: float | None        # joint angle (flexion positive), None if a marker is missing
    twist_deg: float | None        # out-of-plane tilt of the moving marker
    raw_deg: float | None          # orientation before the zero is subtracted
    found: tuple = ()


@dataclass
class AngleTracker:
    fixed_size_mm: float = 16.0
    moving_size_mm: float = 14.0
    sign: int = 1                  # +1 or -1 so that flexion reads positive
    zero_deg: float = 0.0
    _det: object = field(default=None, repr=False)

    def __post_init__(self):
        d = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
        p = cv2.aruco.DetectorParameters()
        p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self._det = cv2.aruco.ArucoDetector(d, p)

    def _markers(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        corners, ids, _ = self._det.detectMarkers(gray)
        out = {}
        if ids is not None:
            for c, i in zip(corners, ids.ravel()):
                out[int(i)] = c.reshape(4, 2).astype(np.float64)
        return out

    def measure(self, frame, t=None) -> AngleReading:
        t = time.time() if t is None else t
        m = self._markers(frame)
        if FIXED_ID not in m or MOVING_ID not in m:
            return AngleReading(t, None, None, None, tuple(sorted(m)))
        s = self.fixed_size_mm
        plane = np.array([[0, 0], [s, 0], [s, s], [0, s]], np.float64)
        H, _ = cv2.findHomography(m[FIXED_ID], plane)
        q = cv2.perspectiveTransform(m[MOVING_ID].reshape(-1, 1, 2), H).reshape(4, 2)
        e01, e12 = q[1] - q[0], q[2] - q[1]
        raw = math.degrees(math.atan2(e01[1], e01[0]))
        a, b = np.linalg.norm(e01), np.linalg.norm(e12)
        twist = math.degrees(math.acos(min(1.0, min(a, b) / max(a, b)))) if max(a, b) > 0 else None
        ang = self.sign * wrap180(raw - self.zero_deg)
        return AngleReading(t, ang, twist, raw, tuple(sorted(m)))

    def set_zero(self, raw_deg):
        self.zero_deg = raw_deg


def wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


# ----------------------------------------------------------------------------- seven-segment
#        a
#      f   b
#        g
#      e   c
#        d
SEGMENTS = {  # (x0, y0, x1, y1) of the sample window inside a unit digit cell
    "a": (0.30, 0.02, 0.70, 0.12), "b": (0.78, 0.15, 0.95, 0.42), "c": (0.78, 0.58, 0.95, 0.85),
    "d": (0.30, 0.88, 0.70, 0.98), "e": (0.05, 0.58, 0.22, 0.85), "f": (0.05, 0.15, 0.22, 0.42),
    "g": (0.30, 0.45, 0.70, 0.55),
}
PATTERNS = {
    "abcdef": "0", "bc": "1", "abdeg": "2", "abcdg": "3", "bcfg": "4", "acdfg": "5",
    "acdefg": "6", "abc": "7", "abcf": "7", "abcdefg": "8", "abcdfg": "9", "g": "-", "": " ",
}


@dataclass
class SevenSegReader:
    corners: list                   # 4 image points (TL, TR, BR, BL) around the digits
    n_digits: int = 4
    decimals: int = 0               # fixed decimal places shown (e.g. 1 for '123.4')
    dark_digits: bool = True        # LCD: dark segments on a light background
    slant_deg: float = 0.0          # italic LCD digits lean right by about 5-10 deg
    gap: float = 0.12               # gap between digit cells, as a fraction of a cell
    on_fraction: float = 0.45       # share of a window that must be "on"
    stable_frames: int = 3
    _hist: list = field(default_factory=list, repr=False)

    W_CELL, H = 60, 100

    def warp(self, frame):
        W = self.W_CELL * self.n_digits
        src = np.array(self.corners, np.float32)
        dst = np.array([[0, 0], [W, 0], [W, self.H], [0, self.H]], np.float32)
        M = cv2.getPerspectiveTransform(src, dst)
        img = cv2.warpPerspective(frame, M, (W, self.H))
        if self.slant_deg:
            k = math.tan(math.radians(self.slant_deg))
            S = np.float32([[1, k, -k * self.H / 2], [0, 1, 0]])
            img = cv2.warpAffine(img, S, (W, self.H), borderMode=cv2.BORDER_REPLICATE)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        flag = cv2.THRESH_BINARY_INV if self.dark_digits else cv2.THRESH_BINARY
        _, bw = cv2.threshold(gray, 0, 255, flag + cv2.THRESH_OTSU)
        return bw

    def decode(self, frame):
        """One frame -> (value or None, text)."""
        bw = self.warp(frame)
        txt = ""
        for i in range(self.n_digits):
            x0 = i * self.W_CELL + self.gap * self.W_CELL / 2
            w = self.W_CELL * (1 - self.gap)
            on = ""
            for seg, (a, b, c, d) in SEGMENTS.items():
                win = bw[int(b * self.H):int(d * self.H), int(x0 + a * w):int(x0 + c * w)]
                if win.size and (win > 0).mean() >= self.on_fraction:
                    on += seg
            txt += PATTERNS.get("".join(sorted(on)), "?")
        s = txt.strip()
        if not s or "?" in s or s in ("-",):
            return None, txt
        try:
            v = int(s.replace(" ", ""))
        except ValueError:
            return None, txt
        return v / 10 ** self.decimals, txt

    def read(self, frame):
        """Stable value: the same decode in `stable_frames` consecutive calls, else None."""
        v, txt = self.decode(frame)
        self._hist = (self._hist + [v])[-self.stable_frames:]
        if v is not None and len(self._hist) == self.stable_frames and all(h == v for h in self._hist):
            return v, txt
        return None, txt


# ----------------------------------------------------------------------------- interactive helpers
def pick_corners(frame, title="click the 4 corners of the digits: TL, TR, BR, BL"):
    """GUI: click four points on a frame; returns them as a list of [x, y]."""
    pts = []
    disp = frame.copy()

    def cb(ev, x, y, *_):
        if ev == cv2.EVENT_LBUTTONDOWN and len(pts) < 4:
            pts.append([float(x), float(y)])
            cv2.circle(disp, (x, y), 5, (0, 0, 255), -1)

    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(title, cb)
    while len(pts) < 4:
        cv2.imshow(title, disp)
        if cv2.waitKey(30) == 27:
            break
    cv2.destroyWindow(title)
    return pts
