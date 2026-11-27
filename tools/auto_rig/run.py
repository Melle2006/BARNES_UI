"""BARNES automated bending rig: one program for setup, the five tests and the results.

    python3 run.py markers                       print-ready ArUco markers (PDF, exact size)
    python3 run.py check                         live view: angle, twist, force (check the setup)
    python3 run.py scale-setup                   mark the scale's digits once (camera force only)
    python3 run.py winch-setup                   find the slack position and the pull direction
    python3 run.py run step1 --module H1-P       run a test (step1 ... step5, or all)
    python3 run.py run step2 --module H1-P --weights 50,100,200
    python3 run.py run step4 --module H2-P --label after1000
    python3 run.py run step5 --module H2-P --cycles 1000 --every 100
    python3 run.py sim step1                     dry run on the simulated joint (no hardware)
    python3 run.py export                        all results -> results/rig_auto/rig_auto_results.xlsx + plots

Settings live in config.yaml (copy config.example.yaml). See README.md for the hardware.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, fields
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
from auto_rig import vision, hardware, procedures  # noqa: E402


def load_cfg(path):
    p = Path(path)
    if not p.exists():
        sys.exit(f"{p} not found: copy config.example.yaml to config.yaml and edit it")
    return yaml.safe_load(p.read_text())


def save_cfg(path, cfg):
    Path(path).write_text(yaml.safe_dump(cfg, sort_keys=False))


def rig_config(c):
    w = c.get("winch", {})
    names = {f.name for f in fields(procedures.RigConfig)}
    return procedures.RigConfig(**{k: v for k, v in w.items() if k in names})


def build_sensors(c, winch=None):
    cam = vision.Camera(c["camera"]["angle"])
    fcam = vision.Camera(c["camera"]["scale"]) if c["camera"].get("scale") not in (None, "", "same") else None
    m = c["markers"]
    tr = vision.AngleTracker(fixed_size_mm=m["fixed_mm"], moving_size_mm=m["moving_mm"], sign=m.get("sign", 1))
    f = c["force"]
    if f["source"] == "hx711":
        src = hardware.HX711Force(winch)
    else:
        rd = vision.SevenSegReader(**f["reader"])
        src = hardware.ScaleCameraForce(rd, unit=f.get("unit", "g"), mode=f.get("mode", "inline"),
                                        tare_reading=f.get("tare", 0.0))
    return hardware.Sensors(cam, tr, src, fcam, winch)


# ----------------------------------------------------------------------------- commands
def cmd_markers(a, c):
    import cv2
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    m = c["markers"] if c else {"fixed_mm": 16, "moving_mm": 14}
    d = cv2.aruco.getPredefinedDictionary(vision.ARUCO_DICT)
    fig = plt.figure(figsize=(210 / 25.4, 297 / 25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 210)
    ax.set_ylim(297, 0)
    ax.axis("off")
    y = 25
    for mid, size, label in ((vision.FIXED_ID, m["fixed_mm"], "FIXED (id 0): on the rig post's finger-side face"),
                             (vision.MOVING_ID, m["moving_mm"], "MOVING (id 1): on the marker flag on the load adapter")):
        img = cv2.aruco.generateImageMarker(d, mid, 600)
        for k in range(3):     # three copies of each
            x = 20 + k * (size + 20)
            ax.imshow(img, cmap="gray", extent=(x, x + size, y + size, y), interpolation="nearest")
            ax.add_patch(plt.Rectangle((x - 3, y - 3), size + 6, size + 6, fill=False, lw=0.3, ls=":"))
        ax.text(20, y + size + 8, f"{label}: black square exactly {size} mm (cut on the dotted line, keep the white border)",
                fontsize=7)
        y += size + 25
    ax.plot([20, 120], [y, y], "k-", lw=1)
    for xx in (20, 70, 120):
        ax.plot([xx, xx], [y - 2, y + 2], "k-", lw=1)
    ax.text(20, y + 7, "Print at 100 % (no 'fit to page'): this bar must measure exactly 100 mm", fontsize=7)
    out = HERE / "markers_A4.pdf"
    fig.savefig(out)
    fig.savefig(out.with_suffix(".png"), dpi=200)
    print("wrote", out)


def cmd_check(a, c):
    import cv2
    sens = build_sensors(c, open_winch(c) if c["force"]["source"] == "hx711" else None)
    print("ESC to quit, z to set the zero (finger straight)")
    while True:
        t, fr = sens.angle_cam.read()
        r = sens.tracker.measure(fr, t)
        f = sens.force_src.read(fr if sens.force_cam is None else sens.force_cam.read()[1])
        txt = (f"angle {r.angle_deg:6.1f} deg  twist {r.twist_deg:4.1f}" if r.angle_deg is not None
               else f"markers seen: {r.found}") + ("   force --" if f is None else f"   force {f:6.2f} N")
        cv2.putText(fr, txt, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        cv2.imshow("auto rig check", fr)
        k = cv2.waitKey(30)
        if k == 27:
            break
        if k == ord("z") and r.raw_deg is not None:
            sens.tracker.set_zero(r.raw_deg)


def cmd_scale_setup(a, c):
    import cv2
    cam = vision.Camera(c["camera"].get("scale") or c["camera"]["angle"]) \
        if c["camera"].get("scale") not in (None, "", "same") else vision.Camera(c["camera"]["angle"])
    _, fr = cam.read()
    pts = vision.pick_corners(fr)
    if len(pts) != 4:
        sys.exit("cancelled")
    rd = c["force"]["reader"]
    rd["corners"] = pts
    rd["n_digits"] = int(input(f"how many digit positions does the display have? [{rd.get('n_digits', 4)}] ") or rd.get("n_digits", 4))
    rd["decimals"] = int(input(f"how many digits after the decimal point? [{rd.get('decimals', 0)}] ") or rd.get("decimals", 0))
    rd["dark_digits"] = (input("dark digits on a light background (LCD)? [Y/n] ").strip().lower() != "n")
    c["force"]["unit"] = input(f"unit shown (g, kg, N, lb) [{c['force'].get('unit', 'g')}] ").strip() or c["force"].get("unit", "g")
    r = vision.SevenSegReader(**rd)
    print("live check: compare with the display. ESC when it reads right (edit slant_deg/gap in config.yaml if not)")
    while True:
        _, fr = cam.read()
        v, txt = r.decode(fr)
        bw = r.warp(fr)
        cv2.imshow("digits (as the program sees them)", bw)
        cv2.putText(fr, f"read: '{txt}' -> {v}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        cv2.imshow("scale", fr)
        if cv2.waitKey(100) == 27:
            break
    t = input("scale reading with NO load on the tendon (tare), e.g. 0 [0] ").strip()
    c["force"]["tare"] = float(t) if t else 0.0
    save_cfg(a.config, c)
    print("saved to", a.config)


def open_winch(c):
    return hardware.SerialWinch(c["winch"]["port"])


def cmd_winch_setup(a, c):
    w = open_winch(c)
    sens = build_sensors(c, w)
    print("Jog the winch: + / - (5 us), ++ / -- (25 us), a number = go to that pulse width.\n"
          "Find where the line JUST goes taut with the finger straight; type 's' there. 'q' quits.")
    pos = w.position_us
    while True:
        smp = sens.read()
        print(f"winch {pos} us | angle {smp.angle_deg} | force {smp.force_n}")
        k = input("> ").strip()
        if k == "q":
            break
        if k == "s":
            taut = pos
            back = int(input("which way slackens it: + or - ? ").strip() == "+")
            c["winch"]["direction"] = -1 if back else 1
            c["winch"]["slack_us"] = taut - c["winch"]["direction"] * 20    # 20 us (~0.5 mm) of slack
            save_cfg(a.config, c)
            print(f"saved: slack_us {c['winch']['slack_us']}, direction {c['winch']['direction']}")
            continue
        step = {"+": 5, "-": -5, "++": 25, "--": -25}.get(k)
        pos = pos + step if step is not None else (int(k) if k.isdigit() else pos)
        w.move_to(pos, 200)


def run_tests(a, rig_cfg, winch, sens, say=print, **clock):
    r = procedures.Runner(winch, sens, rig_cfg, a.module, REPO / a.out, **clock)
    steps = ["step1", "step2", "step3", "step4", "step5"] if a.test == "all" else [a.test]
    res = []
    for s in steps:
        if s == "step2":
            res.append(r.step2(weights_g=[float(x) for x in a.weights.split(",")], hanger_g=a.hanger))
        elif s == "step4":
            res.append(r.step4(target_deg=a.target, hold_s=a.hold, record_s=a.record, label=a.label))
        elif s == "step5":
            res.append(r.step5(cycles=a.cycles, target_deg=a.target, check_every=a.every, period_s=a.period))
        else:
            res.append(getattr(r, s)())
    return res


def cmd_run(a, c):
    w = open_winch(c)
    sens = build_sensors(c, w)
    try:
        run_tests(a, rig_config(c), w, sens)
    finally:
        w.move_to(rig_config(c).slack_us, 300)


def cmd_sim(a, c):
    rig = hardware.SimRig(W_n=0.98 if a.test == "step2" else 0.0, stop_deg=30 if a.test == "step3" else None,
                          buckle_n=13.0 if a.test == "step3" else None)
    cfg = procedures.RigConfig(slack_us=rig.us0, settle_s=0.0)
    a.module = a.module or "SIM"
    run_tests(a, cfg, rig, rig, sleep=rig.sleep, prompt=lambda m: print(m, "(sim: continuing)"),
              now=lambda: rig.t)


def cmd_export(a, c):
    from openpyxl import Workbook
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import csv as _csv
    base = REPO / a.out
    summ = sorted(base.glob("*/*.json"))
    if not summ:
        sys.exit(f"no results in {base}")
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    keys = ["module", "test", "stop_reason", "force_to_30deg_n", "force_to_60deg_n", "max_angle_deg", "rest_deg",
            "largest_W_held_at_30deg_n", "holds_2N_at_30deg", "peak_force_n", "mode", "held_deg", "angle_1s",
            "angle_10s", "angle_60s", "angle_10min", "set_after_10min_deg", "within_5deg", "cycles_done", "csv"]
    ws.append(keys)
    for p in summ:
        d = json.loads(p.read_text())
        ws.append([json.dumps(d[k]) if isinstance(d.get(k), (list, dict)) else d.get(k) for k in keys])
        if d["test"].startswith("step2"):
            w2 = wb["Step 2 points"] if "Step 2 points" in wb.sheetnames else wb.create_sheet("Step 2 points")
            if w2.max_row == 1:
                w2.append(["module", "weight_g", "W_n", "T_liftoff_n", "T_30_n", "T_60_n", "effective_lever_mm", "stop_reason"])
            for q in d["points"]:
                w2.append([d["module"]] + [q.get(k) for k in ("weight_g", "W_n", "T_liftoff_n", "T_30_n", "T_60_n",
                                                               "effective_lever_mm", "stop_reason")])
        if d["test"].startswith("step5"):
            w5 = wb["Step 5 checks"] if "Step 5 checks" in wb.sheetnames else wb.create_sheet("Step 5 checks")
            if w5.max_row == 1:
                w5.append(["module", "cycles", "rest_deg", "T_30_n"])
            for q in d["checks"]:
                w5.append([d["module"], q["cycles"], q["rest_deg"], q["T_30_n"]])
    out = base / "rig_auto_results.xlsx"
    wb.save(out)
    # plots: every step-1 curve (force vs angle) on one chart, every step-4 recovery on another
    for test, xk, yk, xl, yl, name in (("step1", "angle_deg", "force_n", "angle (deg)", "tendon force (N)", "step1_curves.png"),
                                       ("step4", "t", "angle_deg", "time after release (s)", "angle (deg)", "step4_springback.png")):
        fig, ax = plt.subplots(figsize=(8, 5))
        for p in sorted(base.glob(f"*/{test}*.csv")):
            rows = list(_csv.DictReader(open(p)))
            if test == "step4":
                rows = [r for r in rows if r["phase"] == "free" and r["angle_deg"]]
                if not rows:
                    continue
                t0 = float(rows[0]["t"])
                xs = [float(r["t"]) - t0 for r in rows]
            else:
                rows = [r for r in rows if r["phase"] in ("up", "down")]
                xs = [float(r[xk]) for r in rows]
            ys = [float(r[yk]) for r in rows]
            ax.plot(xs, ys, label=p.parent.name, lw=1.2)
        if test == "step4":
            ax.set_xscale("symlog", linthresh=1)
        ax.set_xlabel(xl)
        ax.set_ylabel(yl)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7)
        fig.tight_layout()
        fig.savefig(base / name, dpi=130)
        plt.close(fig)
    print("wrote", out, "and plots in", base)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["markers", "check", "scale-setup", "winch-setup", "run", "sim", "export"])
    ap.add_argument("test", nargs="?", default="step1", choices=["step1", "step2", "step3", "step4", "step5", "all"])
    ap.add_argument("--config", default=str(HERE / "config.yaml"))
    ap.add_argument("--module", default=None, help="sheet label, e.g. H1-P")
    ap.add_argument("--out", default="results/rig_auto")
    ap.add_argument("--weights", default="50,100,200,300,500", help="step 2 fingertip weights, g")
    ap.add_argument("--hanger", type=float, default=0.0, help="fingertip hanger mass, g")
    ap.add_argument("--target", type=float, default=60.0, help="step 4/5 angle, deg")
    ap.add_argument("--hold", type=float, default=60.0)
    ap.add_argument("--record", type=float, default=600.0)
    ap.add_argument("--label", default="first", help="step 4: 'first' or 'after1000'")
    ap.add_argument("--cycles", type=int, default=1000)
    ap.add_argument("--every", type=int, default=100)
    ap.add_argument("--period", type=float, default=2.0)
    a = ap.parse_args()
    if a.command in ("run",) and not a.module:
        sys.exit("--module is required, e.g. --module H1-P")
    c = None if a.command in ("sim",) or (a.command == "markers" and not Path(a.config).exists()) else load_cfg(a.config)
    {"markers": cmd_markers, "check": cmd_check, "scale-setup": cmd_scale_setup, "winch-setup": cmd_winch_setup,
     "run": cmd_run, "sim": cmd_sim, "export": cmd_export}[a.command](a, c)


if __name__ == "__main__":
    main()
