"""
Run the round-2 tendon-load FEA over the TEST_PLAN shortlist, one job at a time,
and commit and push each result as it lands so a container restart loses at most
the run in progress.

One job runs at a time on purpose: SPOOLES is the only direct solver in this
CalculiX build and two concurrent jobs exhausted the container's memory.

    python run_round2_campaign.py              # every job not yet in fea/results/
    python run_round2_campaign.py --no-push
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RESULTS = HERE / "fea" / "results"

ANGLES = (0.0, 60.0)    # 30 deg is added afterwards where time allows
#: (variant, offset) for every TEST_PLAN shortlist row 1-11. A deep copy whose
#: flexure is unchanged shares its as-built run (see fea_round2.py), except where
#: only the deep copy is shortlisted, which then runs with the deep tendon's line.
JOBS = [                                # fast leaf joints first, contact joints last
    ("B3_t200_w30", "as-built"),        # rows 3, 4
    ("B5_t200_a45", "deep"),            # row 5
    ("B1_t200_notch050", "as-built"),   # rows 1, 2
    ("B9_n150", "as-built"),            # rows 10, 11
    ("B8_y00_r150", "as-built"),        # row 7
    ("B8_y20_r125", "as-built"),        # rows 8, 9
    ("B4_t100_a60", "deep"),            # row 6 (rolling radius depends on the offset)
    # Not on the shortlist, but the round-1 winner: does it survive tendon load?
    ("B5_t150_a45", "as-built"),
    ("B5_t150_a45", "deep"),
]


def out_path(name, offset, angle):
    return RESULTS / f"{name}{'_deep' if offset == 'deep' else ''}_{angle:g}deg.json"


def git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def push(path, msg):
    git("add", str(path))
    r = git("commit", "-m", msg)
    if r.returncode:
        print(r.stdout, r.stderr)
        return
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    for wait in (0, 2, 4, 8, 16):
        if wait:
            subprocess.run(["sleep", str(wait)])
        if git("push", "-u", "origin", branch).returncode == 0:
            return
    print("push failed; committed locally")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--angles", nargs="*", type=float, default=list(ANGLES))
    a = ap.parse_args()
    sys.path.insert(0, str(HERE))
    import fea_round2 as R
    for name, offset in JOBS:
        if a.only and name not in a.only:
            continue
        for angle in a.angles:
            p = out_path(name, offset, angle)
            if p.exists():
                continue
            print(f"=== {name} {offset} {angle:g} deg", flush=True)
            try:
                r = R.run(name, angle, offset)
            except Exception:
                traceback.print_exc()
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(r, indent=1))
            cap = r.get("capacity_T")
            print(f"    capacity {cap} N at 12 MPa ({r.get('limited_by')}), {r['wall_s']} s", flush=True)
            if not a.no_push:
                push(p, f"Round-2 FEA: {name}{' deep' if offset == 'deep' else ''} at {angle:g} deg, "
                        f"tendon capacity {cap if cap is None else round(cap, 1)} N at 12 MPa\n\n"
                        "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n"
                        "Claude-Session: https://claude.ai/code/session_019vgzUSPBFKho6TcgkovCJp")


if __name__ == "__main__":
    main()
