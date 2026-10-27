"""Is the self-contact benchmark's interpenetration discretisation, or something else?

The question
------------

The Phase 6 self-contact benchmark converges and the contact plainly engages -- a
1.0 N force that would close the hairpin by about 4.7 mm unopposed closes it by 1.1 mm
against a 1.0 mm gap. But it leaves 0.108 mm of residual interpenetration between the
legs, which is 12 per cent of the 0.9 mm element and roughly five orders of magnitude
more than the penalty formulation accounts for. At the contact pressure and stiffness
involved, penalty penetration should be of order a micron.

So the overlap is not the penalty law being soft. The leading hypothesis is an **edge
contact on a coarse mesh**: the legs are not parallel when they meet, because the
loaded one is bending, so the first thing to touch is a corner and a coarse facet
representation lets it dig in.

That hypothesis makes a prediction. If the overlap is discretisation, it should fall
roughly in proportion to the element size, and ``penetration / element_size`` should
stay about constant. If it is something else -- a contact search tolerance, a
formulation limit, a measurement artefact -- refining will not help and the ratio will
climb.

This script runs the benchmark across a refinement sequence and prints both columns,
so the answer is read off rather than argued about.

    python scripts/selfcontact_refinement.py --sizes 1.2 0.9 0.6 0.45

Why it is a separate script
---------------------------

``phase6_benchmarks.py`` answers "may this capability be enabled here", and its answer
is a verdict. This answers "why not", and its answer is a trend. Mixing them would put
a diagnostic's four solves into the path of anyone who just wanted the capability
registry refreshed.

Nothing here writes to the registry. Whatever the trend shows, self-contact stays
``FAILED`` until a run passes the criterion that was stated before the result was
seen.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from phase6_benchmarks import CONTACT_ATTEMPTS, benchmark_self_contact  # noqa: E402

from barnes_ui.core.fea.contact import ContactFormulation  # noqa: E402
from barnes_ui.core.fea.solver import find_solver, probe_solver  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--sizes", type=float, nargs="+", default=[1.2, 0.9, 0.6, 0.45],
        help="Element sizes in mm, coarsest first.",
    )
    parser.add_argument(
        "--all-formulations", action="store_true",
        help=(
            "Try every contact formulation at every size. Off by default: Phase 6 "
            "already established that node-to-surface does not converge on this "
            "problem, and re-establishing it at four mesh densities costs hours of "
            "solver time to learn nothing new."
        ),
    )
    parser.add_argument(
        "--control", action="store_true",
        help=(
            "Also run the identical model with the contact pair removed, as a "
            "control. Without it, 'the legs stopped' cannot be distinguished from "
            "'the legs were never going to meet'."
        ),
    )
    parser.add_argument("--archive", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    solver = find_solver()
    if solver is None:
        raise SystemExit(
            "CalculiX was not found. See docs/08-calculix-installation.md."
        )
    solver = probe_solver(solver)
    print(solver.describe(), flush=True)

    rows = []
    for size in args.sizes:
        print(f"\n=== element size {size} mm ===", flush=True)
        started = time.perf_counter()
        attempts = (
            CONTACT_ATTEMPTS if args.all_formulations
            else tuple(
                a for a in CONTACT_ATTEMPTS
                if a[1] is ContactFormulation.SURFACE_TO_SURFACE
            )
        )
        try:
            outcome = benchmark_self_contact(
                solver, args.archive, element_size=size, attempts=attempts
            )
        except Exception as exc:  # noqa: BLE001 - a crash is a data point
            rows.append({
                "element_size_mm": size,
                "error": f"{type(exc).__name__}: {exc}",
            })
            print(f"raised {type(exc).__name__}: {exc}", flush=True)
            continue
        elapsed = time.perf_counter() - started

        penetration = (
            -outcome.measured if outcome.measured is not None and outcome.measured < 0
            else 0.0
        )
        rows.append({
            "element_size_mm": size,
            "passed": outcome.passed,
            "separation_mm": outcome.measured,
            "penetration_mm": penetration,
            "penetration_over_element": (
                penetration / size if size > 0 else None
            ),
            "convergence": outcome.convergence,
            "run_directory": outcome.run_directory,
            "wall_seconds": round(elapsed, 1),
            "evidence": outcome.evidence,
        })
        print(
            f"penetration {penetration:.5g} mm = {penetration / size * 100:.1f} % "
            f"of an element  ({elapsed:.0f} s)",
            flush=True,
        )

    print()
    print(f"{'size (mm)':>10}{'penetration (mm)':>20}{'as % of element':>18}")
    usable = [r for r in rows if r.get("penetration_over_element") is not None]
    for row in usable:
        print(
            f"{row['element_size_mm']:10.3f}"
            f"{row['penetration_mm']:20.5g}"
            f"{row['penetration_over_element'] * 100:17.1f}%"
        )

    control = None
    if args.control and usable:
        size = usable[len(usable) // 2]["element_size_mm"]
        print(f"\n=== control: no contact pair, element size {size} mm ===",
              flush=True)
        attempts = tuple(
            a for a in CONTACT_ATTEMPTS
            if a[1] is ContactFormulation.SURFACE_TO_SURFACE
        )[:1]
        outcome = benchmark_self_contact(
            solver, args.archive, element_size=size, attempts=attempts,
            with_contact=False,
        )
        control = {
            "element_size_mm": size,
            "separation_mm": outcome.measured,
            "convergence": outcome.convergence,
            "run_directory": outcome.run_directory,
        }
        print(
            f"separation without contact {outcome.measured:+.5g} mm "
            f"({outcome.convergence})",
            flush=True,
        )

    verdict = ""
    if len(usable) >= 2 and all(r["penetration_mm"] <= 0.0 for r in usable):
        separations = [r["separation_mm"] for r in usable]
        verdict = (
            f"No interpenetration at any element size: the closest approach is "
            f"{min(separations):+.4g} to {max(separations):+.4g} mm across a "
            f"{usable[0]['element_size_mm'] / usable[-1]['element_size_mm']:.1f}x "
            "refinement, and it is positive throughout. Mesh-independent and on the "
            "correct side of zero is what a working contact looks like."
        )
        if control is not None and control["separation_mm"] is not None:
            verdict += (
                f" The control, with the contact pair removed, gives "
                f"{control['separation_mm']:+.4g} mm at the same mesh, so the legs "
                "were stopped by the contact rather than by their own stiffness."
            )
    elif len(usable) >= 2:
        ratios = [r["penetration_over_element"] for r in usable]
        spread = max(ratios) / min(ratios) if min(ratios) > 0 else float("inf")
        coarse, fine = usable[0], usable[-1]
        shrink = (
            coarse["penetration_mm"] / fine["penetration_mm"]
            if fine["penetration_mm"] > 0 else float("inf")
        )
        refinement = coarse["element_size_mm"] / fine["element_size_mm"]
        if spread < 1.6:
            verdict = (
                f"Penetration is a near-constant {min(ratios) * 100:.0f} to "
                f"{max(ratios) * 100:.0f} per cent of an element across a "
                f"{refinement:.1f}x refinement, so it IS discretisation: it falls "
                f"with the mesh, and the absolute overlap shrank by {shrink:.1f}x. "
                "The criterion asks for 5 per cent of an element, which this does "
                "not reach at any size tried -- so the verdict stands, but the cause "
                "is an edge contact resolved by the mesh rather than a limit of the "
                "formulation."
            )
        else:
            verdict = (
                f"The ratio to element size varies by {spread:.1f}x across the "
                "sequence, so the overlap does NOT simply scale with the mesh. "
                "Refining is not the fix, and the edge-contact explanation is wrong "
                "or incomplete."
            )

    if verdict:
        print()
        print(verdict)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(
                {"rows": rows, "control": control, "verdict": verdict}, indent=2
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
