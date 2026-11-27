"""Winch, force and angle sources for the automated rig, and a simulated rig for dry runs.

Everything the test sequences need goes through two objects:

* a ``Winch`` (``move_to(us, ms)``, ``position_us``), real (``SerialWinch``) or simulated, and
* a ``Sensors`` object whose ``read()`` returns a ``Sample`` (time, angle, twist, force).

The real sensors combine the camera angle with one force source: the scale display read by the
camera (``ScaleCameraForce``) or a load cell on the winch Arduino's HX711 (``HX711Force``).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

G = 9.80665


@dataclass
class Sample:
    t: float
    angle_deg: float | None
    twist_deg: float | None
    force_n: float | None
    winch_us: int | None = None


# ----------------------------------------------------------------------------- real winch
class SerialWinch:
    """Talks to firmware/auto_rig_winch/auto_rig_winch.ino."""

    def __init__(self, port, baud=115200, timeout=2.0):
        import serial  # pyserial
        self.ser = serial.Serial(port, baud, timeout=timeout)
        time.sleep(2.0)                     # the Uno resets when the port opens
        self.ser.reset_input_buffer()
        self.position_us = self.query()[0]

    def _cmd(self, line, expect="OK"):
        self.ser.write((line + "\n").encode())
        while True:
            r = self.ser.readline().decode(errors="ignore").strip()
            if not r:
                raise TimeoutError(f"no reply to {line!r}")
            if r.startswith("ERR"):
                raise RuntimeError(r)
            if r.startswith(expect):
                return r

    def move_to(self, us, ms=300):
        us = int(round(us))
        self._cmd(f"P {us} {int(ms)}", "OK")
        self.position_us = us

    def query(self):
        """(position_us, force_grams or None)."""
        r = self._cmd("Q", "S").split()
        g = None if r[2] == "NA" else float(r[2])
        return int(r[1]), g

    def tare(self):
        self._cmd("T", "OK")

    def detach(self):
        self._cmd("D", "OK")

    def attach(self):
        self._cmd("A", "OK")


# ----------------------------------------------------------------------------- force sources
class HX711Force:
    """Load cell read by the winch Arduino (in grams, calibrated in the firmware)."""

    def __init__(self, winch):
        self.winch = winch

    def read(self, frame=None):
        _, g = self.winch.query()
        return None if g is None else g * G / 1000.0


class ScaleCameraForce:
    """The scale's display read by the camera. mode 'inline': the scale is in the tendon line and
    reads the tension; 'platform': the winch stands on a platform scale and the line pulls up
    from it, so tension = tare - reading."""

    def __init__(self, reader, unit="g", mode="inline", tare_reading=0.0):
        self.reader, self.unit, self.mode, self.tare_reading = reader, unit, mode, tare_reading

    def to_newton(self, v):
        return {"g": v * G / 1000.0, "kg": v * G, "N": v, "lb": v * 4.448222}[self.unit]

    def read(self, frame):
        v, _ = self.reader.read(frame)
        if v is None:
            return None
        v = (self.tare_reading - v) if self.mode == "platform" else (v - self.tare_reading)
        return self.to_newton(v)


class Sensors:
    def __init__(self, angle_cam, tracker, force_src, force_cam=None, winch=None):
        self.angle_cam, self.tracker, self.force_src = angle_cam, tracker, force_src
        self.force_cam = force_cam            # None: same camera as the angle
        self.winch = winch

    def read(self) -> Sample:
        t, frame = self.angle_cam.read()
        a = self.tracker.measure(frame, t)
        fframe = frame if self.force_cam is None else self.force_cam.read()[1]
        f = self.force_src.read(fframe)
        return Sample(t, a.angle_deg, a.twist_deg, f, getattr(self.winch, "position_us", None))


# ----------------------------------------------------------------------------- simulation
class SimRig:
    """A joint, tendon and winch with simple physics, for dry-running the test sequences.

    Moment balance about the PIP: T * lever = k * theta + W * L * cos(theta), plus a collar stop
    at theta_max and a friction band (hysteresis). The line is slack until the winch has taken in
    `slack_mm`; after that it stretches with compliance `c_mm_per_n`. Sideways buckling sets in
    above `buckle_n` (twist grows, angle drops)."""

    def __init__(self, lever_mm=2.75, k_nmm_per_rad=5.0, theta_max_deg=74.0, W_n=0.0, L_mm=44.8,
                 friction_n=0.15, buckle_n=None, slack_mm=1.0, c_mm_per_n=0.02,
                 mm_per_us=0.0244, us0=1200, noise_deg=0.15, noise_n=0.02, stop_deg=None, seed=1):
        import random
        self.r = random.Random(seed)
        self.__dict__.update(dict(lever=lever_mm, k=k_nmm_per_rad, tmax=math.radians(theta_max_deg),
                                  W=W_n, L=L_mm, fr=friction_n, buckle=buckle_n, slack=slack_mm,
                                  c=c_mm_per_n, mmus=mm_per_us, us0=us0, nd=noise_deg, nf=noise_n,
                                  stop=None if stop_deg is None else math.radians(stop_deg)))
        self.position_us = us0
        self.theta = 0.0
        self.T = 0.0
        self.t = 0.0
        self.buckled = False
        self.free_since = 0.0
        self.theta_rel = 0.0

    # winch interface
    def move_to(self, us, ms=300):
        self.position_us = int(round(us))
        self.t += ms / 1000.0
        self._solve()

    # sensors interface
    def read(self):
        self.t += 0.1
        self._relax()
        a = math.degrees(self.theta) + self.r.gauss(0, self.nd)
        tw = (25.0 if self.buckled else 0.5) + self.r.gauss(0, 0.3)
        f = max(0.0, self.T + self.r.gauss(0, self.nf))
        return Sample(self.t, a, tw, f, self.position_us)

    def sleep(self, s):
        self.t += s

    def _need(self, th):
        return (self.k * th + self.W * self.L * math.cos(th)) / self.lever

    def _solve(self):
        x = (self.position_us - self.us0) * self.mmus - self.slack     # line taken in beyond slack
        if x <= 0:
            self.T = 0.0
            if self.free_since is None:
                self.free_since = self.t
                self.theta_rel = self.theta
            return
        self.free_since = None
        lo = 0.0
        hi = self.stop if self.stop is not None else self.tmax
        # line geometry: x = lever * theta + c * T, with T >= need(theta) (+/- friction)
        th = self.theta
        for _ in range(60):
            T = max(0.0, (x - self.lever * th) / self.c)
            need = self._need(th)
            if T > need + self.fr and th < hi:
                th = min(hi, th + 0.002)
            elif T < need - self.fr and th > lo:
                th = max(lo, th - 0.002)
            else:
                break
        self.theta = th
        self.T = max(0.0, (x - self.lever * th) / self.c)
        if self.buckle and self.T > self.buckle:
            self.buckled = True
            self.theta = max(0.0, self.theta - math.radians(8))
            self.T *= 0.6

    def _relax(self):
        """Free spring-back when the line is slack: 85 % elastic within about a second, the rest
        viscous (time constant 60 s), to a 2 deg permanent set."""
        if self.free_since is None or self.T > 0:
            return
        dt = self.t - self.free_since
        sett = math.radians(2.0)
        th0 = self.theta_rel
        frac = 0.85 * math.exp(-dt / 0.3) + 0.15 * math.exp(-dt / 60.0)
        self.theta = max(0.0, sett + (th0 - sett) * frac) if th0 > sett else th0
