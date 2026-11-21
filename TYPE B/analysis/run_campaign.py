"""
Run the FEA protocol in fea_typeb.py over many variants, in parallel.

    python run_campaign.py PIP                       # every variant at the PIP
    python run_campaign.py MCP B3_t150_w30 B1_t100_notch100
    python run_campaign.py PIP --workers 2 --threads 2

Each result is written to results/<joint>/<variant>.json; a variant that already
has a result is skipped, so an interrupted campaign resumes where it stopped.
"""

import argparse
import json
import sys
import tempfile
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def one(name, joint, threads, scratch):
    import fea_typeb as T
    out = HERE / "results" / joint / f"{name}.json"
    work = Path(tempfile.mkdtemp(prefix=f"{name}_{joint}_", dir=scratch))
    t0 = time.time()
    try:
        r = T.run_joint(name, joint, work, threads=threads)
        r["error"] = None
    except Exception as exc:  # recorded, not hidden: a failed run is a result too
        r = dict(variant=name, joint=joint, error=f"{exc}\n{traceback.format_exc()[-1500:]}")
    r["wall_s"] = round(time.time() - t0, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(r, indent=1))
    return name, r.get("error"), r["wall_s"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("joint", choices=["MCP", "PIP", "DIP"])
    ap.add_argument("variants", nargs="*")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--scratch", default=tempfile.gettempdir())
    ap.add_argument("--order", default="fast-first", choices=["fast-first", "as-listed"])
    a = ap.parse_args()
    import fea_typeb as T
    names = a.variants or list(T.all_variants())
    todo = [n for n in names if not (HERE / "results" / a.joint / f"{n}.json").exists()]
    if a.order == "fast-first":
        todo.sort(key=lambda n: n.startswith("B_") or n.startswith("B00"))   # lattice last
    print(f"{len(todo)} to run at the {a.joint}", flush=True)
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(one, n, a.joint, a.threads, a.scratch) for n in todo]
        for f in as_completed(futs):
            n, err, wall = f.result()
            print(f"{time.strftime('%H:%M:%S')} {n}: {'ERROR ' + err.splitlines()[0] if err else 'ok'} ({wall:.0f} s)",
                  flush=True)


if __name__ == "__main__":
    main()
