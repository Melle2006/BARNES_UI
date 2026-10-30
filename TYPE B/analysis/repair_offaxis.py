"""
One-off repair: re-read the off-axis stiffnesses of finished runs with the
time-based parser (the first campaign runs read prints by position, which is
wrong when CalculiX cut a step into increments).

    python repair_offaxis.py JOINT SCRATCH_DIR
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fea_typeb as T  # noqa: E402

joint, scratch = sys.argv[1], Path(sys.argv[2])
for p in sorted((Path(__file__).resolve().parent / "results" / joint).glob("*.json")):
    r = json.loads(p.read_text())
    runs = sorted(scratch.glob(f"{r['variant']}_{joint}_*/offaxis.dat"), key=lambda q: q.stat().st_mtime)
    if not runs:
        print(r["variant"], "no off-axis output kept")
        continue
    off = T.parse_dat(runs[-1])
    k = T.offaxis_stiffness(off.get(("forces", "ROT"), []), off.get(("forces", "REF"), []))
    print(r["variant"], {a: round(r.get(a) or 0, 1) for a in k}, "->", {a: round(b, 1) for a, b in k.items()})
    r.update(k)
    p.write_text(json.dumps(r, indent=1))
