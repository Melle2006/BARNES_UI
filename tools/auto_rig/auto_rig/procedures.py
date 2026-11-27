"""The five rig tests (docs/12, Part 2), driven by the winch and measured by the camera.

Each test writes a CSV of every reading and returns a summary dict with the numbers the workbook
asks for. The only things a person does: hang the fingertip weight for step 2, place the stop for
step 3, and start each test.

Safety on every move: the winch stops and returns to slack if the force passes `max_force_n`, the
angle passes `max_angle_deg`, the moving marker twists more than `twist_limit_deg` (sideways
buckling), or the markers are lost for `lost_limit` readings in a row.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class RigConfig:
    slack_us: int = 1200          # winch position with the line just slack, finger at rest
    direction: int = 1            # +1 if increasing pulse width pulls the tendon in
    step_us: int = 4              # winch step for the quasi-static tests (~0.1 mm of line)
    fast_ms: int = 150            # time for a fast move (release)
    settle_s: float = 1.2         # wait after each step before reading (scale display update)
    samples: int = 3              # readings averaged per step (median)
    max_travel_us: int = 900      # never pull further than this beyond slack
    max_force_n: float = 47.0     # the servo's limit; lower it if the rig cannot take it
    max_angle_deg: float = 85.0   # set just under the module's collar contact
    twist_limit_deg: float = 6.0  # sideways buckling / twist detector
    lost_limit: int = 5
    lever_hook_mm: float = 44.8


@dataclass
class Result:
    test: str
    module: str
    csv: str
    summary: dict = field(default_factory=dict)


class Runner:
    def __init__(self, winch, sensors, cfg: RigConfig, module: str, out_dir: Path,
                 sleep=time.sleep, prompt=input, say=print, now=time.time):
        self.w, self.s, self.cfg, self.module = winch, sensors, cfg, module
        self.now = now
        self.out = Path(out_dir) / module
        self.out.mkdir(parents=True, exist_ok=True)
        self.sleep, self.prompt, self.say = sleep, prompt, say
        self.rows, self.test = [], ""

    # ------------------------------------------------------------------ basics
    def pos(self, k):
        return self.cfg.slack_us + self.cfg.direction * k * self.cfg.step_us

    def read_settled(self, phase, note=""):
        self.sleep(self.cfg.settle_s)
        got, lost = [], 0
        while len(got) < self.cfg.samples:
            smp = self.s.read()
            if smp.angle_deg is None or smp.force_n is None:
                lost += 1
                if lost >= self.cfg.lost_limit:
                    raise RuntimeError("markers or scale display lost: check the camera view")
                self.sleep(0.2)
                continue
            got.append(smp)
        a = statistics.median(x.angle_deg for x in got)
        tw = statistics.median(x.twist_deg for x in got if x.twist_deg is not None) if any(
            x.twist_deg is not None for x in got) else None
        f = statistics.median(x.force_n for x in got)
        row = dict(t=round(got[-1].t, 3), phase=phase, winch_us=getattr(self.w, "position_us", None),
                   angle_deg=round(a, 2), twist_deg=None if tw is None else round(tw, 2),
                   force_n=round(f, 3), note=note)
        self.rows.append(row)
        return row

    def safe(self, row):
        c = self.cfg
        if row["force_n"] >= c.max_force_n:
            return f"force limit {c.max_force_n} N"
        if row["angle_deg"] >= c.max_angle_deg:
            return f"angle limit {c.max_angle_deg} deg"
        if row["twist_deg"] is not None and row["twist_deg"] >= c.twist_limit_deg:
            return f"twist {row['twist_deg']:.1f} deg (sideways buckling)"
        return None

    def release(self):
        self.w.move_to(self.cfg.slack_us, self.cfg.fast_ms)

    def start(self, test):
        self.test, self.rows = test, []
        self.say(f"[{self.module}] {test}")

    def save(self, summary):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = self.out / f"{self.test}_{stamp}.csv"
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(self.rows[0]) if self.rows else ["t"])
            w.writeheader()
            w.writerows(self.rows)
        summary = dict(module=self.module, test=self.test, csv=str(path), **summary)
        with open(self.out / f"{self.test}_{stamp}.json", "w") as f:
            json.dump(summary, f, indent=1)
        self.say(json.dumps(summary, indent=1))
        return Result(self.test, self.module, str(path), summary)

    def zero(self):
        """Finger straight (rest block in, or at rest), line slack: record the angle zero."""
        self.release()
        self.sleep(2.0)
        if hasattr(self.s, "tracker"):
            raws = []
            for _ in range(10):
                t, fr = self.s.angle_cam.read()
                r = self.s.tracker.measure(fr, t)
                if r.raw_deg is not None:
                    raws.append(r.raw_deg)
            if not raws:
                raise RuntimeError("markers not visible")
            self.s.tracker.set_zero(statistics.median(raws))

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def force_at(rows, angle):
        """Force where the angle first reaches `angle` (linear interpolation)."""
        for a, b in zip(rows, rows[1:]):
            if a["angle_deg"] < angle <= b["angle_deg"]:
                f = (angle - a["angle_deg"]) / (b["angle_deg"] - a["angle_deg"])
                return round(a["force_n"] + f * (b["force_n"] - a["force_n"]), 3)
        return None

    def pull_until(self, phase, done, k0=0):
        """Step the winch in until done(row) is true, a limit trips, or travel runs out.
        Returns (rows_of_this_pull, reason, k)."""
        rows, k = [], k0
        while True:
            k += 1
            if k * self.cfg.step_us > self.cfg.max_travel_us:
                return rows, "winch travel limit", k
            self.w.move_to(self.pos(k), 120)
            row = self.read_settled(phase)
            rows.append(row)
            why = self.safe(row)
            if why:
                return rows, why, k
            if done(row, rows):
                return rows, "done", k

    # ------------------------------------------------------------------ step 1
    def step1(self):
        """Free closing curve: no fingertip weight, no rest block. Up until the angle stops
        rising (collars met) or a limit; then back down the same steps."""
        self.start("step1_free_curve")
        self.prompt("Step 1: no fingertip hanger, rest block OUT, coupler/finger free. Enter to start")
        self.zero()
        rest = self.read_settled("rest")["angle_deg"]

        def plateau(row, rows):
            if len(rows) < 4 or row["force_n"] < 0.5:
                return False
            return rows[-1]["angle_deg"] - rows[-4]["angle_deg"] < 1.0

        up, why, k = self.pull_until("up", plateau)
        down = []
        for kk in range(k - 1, -1, -1):
            self.w.move_to(self.pos(kk), 120)
            down.append(self.read_settled("down"))
        self.release()
        self.sleep(30)
        end = self.read_settled("rest_after", "after 30 s")
        loop_area = None
        if up and down:
            a_up = {r["winch_us"]: r for r in up}
            diffs = [abs(a_up[r["winch_us"]]["angle_deg"] - r["angle_deg"]) for r in down if r["winch_us"] in a_up]
            loop_area = round(max(diffs), 2) if diffs else None
        return self.save(dict(stop_reason=why, rest_deg=rest, max_angle_deg=max(r["angle_deg"] for r in up),
                              force_to_30deg_n=self.force_at(up, 30.0), force_to_60deg_n=self.force_at(up, 60.0),
                              max_force_n=max(r["force_n"] for r in up), widest_hysteresis_deg=loop_area,
                              rest_after_deg=end["angle_deg"] if end else None))

    # ------------------------------------------------------------------ step 2
    def step2(self, weights_g=(50, 100, 200, 300, 500), hanger_g=0.0, liftoff_deg=1.0):
        """Fingertip force held: for each weight, pull to lift-off, 30 and 60 deg."""
        self.start("step2_fingertip")
        out = []
        for wg in weights_g:
            self.release()
            self.prompt(f"Step 2: rest block IN, hang {wg} g on the {self.cfg.lever_hook_mm} mm hole "
                        f"(hanger included: {hanger_g} g). Enter to start")
            self.zero()
            W = (wg + hanger_g) * 9.80665 / 1000.0
            res = dict(weight_g=wg, W_n=round(W, 3))
            rows, why, k = self.pull_until(f"W{wg}", lambda r, rs: r["angle_deg"] >= 60.0)
            res["T_liftoff_n"] = self.force_at([dict(angle_deg=-1e9, force_n=0)] + rows, liftoff_deg)
            res["T_30_n"] = self.force_at(rows, 30.0)
            res["T_60_n"] = self.force_at(rows, 60.0)
            res["stop_reason"] = why
            if res["T_liftoff_n"]:
                res["effective_lever_mm"] = round(W * self.cfg.lever_hook_mm / res["T_liftoff_n"], 2)
            out.append(res)
            self.release()
            self.say(res)
            if why.startswith(("force", "twist", "winch")) and res["T_30_n"] is None:
                self.say("could not reach 30 deg: heavier weights skipped")
                break
        held = [r["W_n"] for r in out if r["T_30_n"] is not None and r["T_30_n"] <= self.cfg.max_force_n]
        return self.save(dict(points=out, largest_W_held_at_30deg_n=max(held) if held else 0.0,
                              holds_2N_at_30deg=bool(held and max(held) >= 2.0)))

    # ------------------------------------------------------------------ step 3
    def step3(self, steady_g=100):
        """Where it gives way: the adapter pressed up against a stop at 30 deg; pull until the
        force drops (buckle/squash), it twists, the angle falls, or the force limit."""
        self.start("step3_give_way")
        self.release()
        self.prompt(f"Step 3: clamp the stop ABOVE the adapter at 30 deg, {steady_g} g on the hook. Enter")
        self.zero()
        peak, at_stop = 0.0, False

        def failed(row, rows):
            nonlocal peak, at_stop
            if row["angle_deg"] >= 27.0:
                at_stop = True                               # adapter is against the stop
            if not at_stop:
                return False
            peak = max(peak, row["force_n"])
            if row["angle_deg"] < 22.0:                      # fell back off the stop: collapsed
                return True
            return peak > 2.0 and row["force_n"] < 0.85 * peak

        rows, why, k = self.pull_until("load", failed)
        if why == "done":
            last = rows[-1]
            mode = "buckle (force dropped)" if last["angle_deg"] >= 25 else "collapse (angle fell)"
        elif why.startswith("twist"):
            mode = "twist / sideways buckle"
        elif why.startswith("force"):
            mode = f"none up to {self.cfg.max_force_n} N"
        else:
            mode = why
        self.release()
        self.sleep(60)
        after = self.read_settled("rest_1min_after")
        return self.save(dict(peak_force_n=round(peak, 2), mode=mode, stop_reason=why,
                              rest_1min_after_deg=after["angle_deg"]))

    # ------------------------------------------------------------------ step 4
    def step4(self, target_deg=60.0, hold_s=60.0, record_s=600.0, label="first"):
        """Spring-back: pull to target, hold, release fast (line slack), log the angle."""
        self.start(f"step4_springback_{label}")
        self.prompt("Step 4: no fingertip hanger, rest block OUT. Enter to start")
        self.zero()
        rest = self.read_settled("rest")["angle_deg"]
        rows, why, k = self.pull_until("to_target", lambda r, rs: r["angle_deg"] >= target_deg)
        t0 = self.now()
        held = None
        while self.now() - t0 < hold_s:
            held = self._sample("hold")
            self.sleep(2.0)
        self.release()
        tr = self.now()
        marks, got = [1, 10, 60, 600], {}
        while self.now() - tr < record_s:
            smp = self._sample("free")
            dt = self.now() - tr
            for m in marks:
                if m not in got and dt >= m and smp["angle_deg"] is not None:
                    got[m] = smp["angle_deg"]
            self.sleep(0.1 if dt < 15 else 1.0)
        a10 = got.get(600)
        return self.save(dict(rest_deg=rest, held_deg=held and held["angle_deg"],
                              force_at_hold_end_n=held and held["force_n"], stop_reason=why,
                              angle_1s=got.get(1), angle_10s=got.get(10), angle_60s=got.get(60),
                              angle_10min=a10, set_after_10min_deg=None if a10 is None else round(a10 - rest, 2),
                              within_5deg=None if a10 is None else abs(a10 - rest) <= 5.0))

    def _sample(self, phase):
        smp = self.s.read()
        row = dict(t=round(smp.t, 3), phase=phase, winch_us=getattr(self.w, "position_us", None),
                   angle_deg=None if smp.angle_deg is None else round(smp.angle_deg, 2),
                   twist_deg=None if smp.twist_deg is None else round(smp.twist_deg, 2),
                   force_n=None if smp.force_n is None else round(smp.force_n, 3), note="")
        self.rows.append(row)
        return row

    # ------------------------------------------------------------------ step 5
    def step5(self, cycles=1000, target_deg=60.0, check_every=100, period_s=2.0, fingertip_g=0.0,
              stop_change_pct=20.0, stop_rest_deg=5.0):
        """Tendon-driven cycles 0 -> target with the winch; every `check_every` cycles: resting
        angle (line slack 30 s) and the tension to reach 30 deg (slow pull)."""
        self.start("step5_cycles")
        self.prompt(f"Step 5: rest block OUT, fingertip weight {fingertip_g} g. Enter to start")
        self.zero()
        rows, why, k_target = self.pull_until("find_target", lambda r, rs: r["angle_deg"] >= target_deg)
        self.release()
        target_us = self.pos(k_target)
        checks = []

        def check(n):
            self.release()
            self.sleep(30)
            rest = self.read_settled(f"check{n}_rest")["angle_deg"]
            pr, _, _ = self.pull_until(f"check{n}_pull", lambda r, rs: r["angle_deg"] >= 30.0)
            self.release()
            c = dict(cycles=n, rest_deg=rest, T_30_n=self.force_at(pr, 30.0))
            checks.append(c)
            self.say(c)
            return c

        base = check(0)
        stop = f"{cycles} cycles"
        half_ms = int(period_s * 500)
        for n in range(1, cycles + 1):
            self.w.move_to(target_us, half_ms)
            self.w.move_to(self.cfg.slack_us, half_ms)
            if n % check_every == 0:
                c = check(n)
                if base["T_30_n"] and c["T_30_n"] and abs(c["T_30_n"] - base["T_30_n"]) / base["T_30_n"] * 100 >= stop_change_pct:
                    stop = f"T to 30 deg changed {stop_change_pct}% at {n}"
                    break
                if abs(c["rest_deg"] - base["rest_deg"]) >= stop_rest_deg:
                    stop = f"resting angle changed {stop_rest_deg} deg at {n}"
                    break
        return self.save(dict(target_deg=target_deg, target_us=target_us, checks=checks, stop_reason=stop,
                              cycles_done=checks[-1]["cycles"] if checks else 0))
