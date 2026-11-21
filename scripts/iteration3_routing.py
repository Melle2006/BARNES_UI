"""Type A tendon routing for the iteration 3 index finger, with a stand-in distal phalanx.

    python scripts/iteration3_routing.py

PROVISIONAL: the iteration 3 assembly (reference_parts/iteration3_hand_assembly.step)
has no distal phalanx. Until it exists, the old index DP stands in, scaled:

* its length and hole stations by the middle phalanx's length ratio,
  21.34 / 26.535 = 0.804 (iteration 3 MP / old MP);
* its palmar depth (how deep a tendon guide can sit) by the ratio of the two middle
  phalanges' palmar depth.

Everything else is measured from iteration 3, in the A8 study frame of
scripts/iteration3_frame.py (origin at the MCP ball, +Y along the proximal phalanx,
+Z the back of the finger, the middle phalanx straightened): the MCP ball, the PIP
and DIP pins, the proximal and middle phalanges and the index metacarpal (MC2) for the
guide depth limits and holes, and the MCP and PIP flexion stops. The DIP range is the
anatomical 90 degrees (no DP to stop it). The MCP stops at 39 degrees in the CAD (the
MC2 socket wraps the ball to 6 mm past its centre), so the routing is run as drawn and
with the socket relieved to the anatomical 90 degrees. The joint heads are 7.4 mm in radius (the
joint envelope about each pin; the MCP ball is 7.25 mm).

The analysis itself is scripts/tendon_routing_analysis.py, unchanged: every guide
position on each link, worst torque margin over the grasp against a 5 N fingertip
load, single tendon sharing one servo's tension and stroke. The joint spring is the
iteration 3 A8 or A6 as a secant stiffness (torque at full flexion over the angle),
run once for each, because they differ by eight times.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "src"), str(REPO / "scripts")]

import tendon_routing_analysis as T  # noqa: E402
import type_a_geometry as G  # noqa: E402
from barnes_ui.core.assembly.loader import load_step_assembly  # noqa: E402
from barnes_ui.core.cad.registry import load_geometry  # noqa: E402
from barnes_ui.core.cad.tessellate import tessellate_shape  # noqa: E402

IT3 = REPO / "results" / "iteration3"
OUT = IT3 / "routing"
OLD = REPO / "results" / "tendon_routing" / "type_a_geometry.json"
PIN_Y, DIP_FROM_PIP = 39.18, 21.34
JOINT_HEAD_R = 7.4

#: The two iteration 3 springs as secant stiffness, N.m/rad (torque at full flexion over
#: the angle, at 12 MPa): A8 selected, 1.24 N.mm at 90 deg; A6 selected (R60), 12.3 N.mm
#: at 105 deg.
SPRINGS_12 = {"A8": 1.24e-3 / math.radians(90), "A6": 12.27e-3 / math.radians(105)}
#: The springs at the measured modulus (results/sunlu_rescale/basis.json: E_sunlu_mpa, from the
#: specimen tests; falls back to the provisional 12 MPa).
_BASIS = json.loads((REPO / "results/sunlu_rescale/basis.json").read_text())
E_SPRING_MPA = _BASIS.get("E_sunlu_mpa") or 12.0
SPRINGS = {k: v * E_SPRING_MPA / 12.0 for k, v in SPRINGS_12.items()}


def transformed(shape, R, t):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf
    tr = gp_Trsf()
    tr.SetValues(*R[0], t[0], *R[1], t[1], *R[2], t[2])
    return BRepBuilderAPI_Transform(shape, tr, True).Shape()


def compound(shapes):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    c, b = TopoDS_Compound(), BRep_Builder()
    b.MakeCompound(c)
    for s in shapes:
        b.Add(c, s)
    return c


def geometry():
    fr = json.loads((IT3 / "frame.json").read_text())["iteration3"]
    R, t = np.array(fr["R"]), np.array(fr["t"])
    names = G.product_names((REPO / "reference_parts/iteration3_hand_assembly.step").read_text(errors="replace"))
    parts = {names.get(c.name, c.name): c.shape
             for c in load_step_assembly(REPO / "reference_parts/iteration3_hand_assembly.step").parts()}
    mc = transformed(parts["MC2 Body"], R, t)
    pps = [s.shape for s in load_geometry(IT3 / "Index_PP_study.step").solids]
    mp = load_geometry(IT3 / "Index_MP_study.step").solids[0].shape
    pp = compound(pps)
    a = np.array([1.0, 0.0, 0.0])
    palmar = np.array([0.0, 0.0, -1.0])
    mcp, pip, dip = np.zeros(3), np.array([0, PIN_Y, 0.0]), np.array([0, PIN_Y + DIP_FROM_PIP, 0.0])
    u = np.array([0.0, 1.0, 0.0])
    # metacarpal axis: principal axis of MC2, in the finger's plane, pointing to the MCP
    v = np.asarray(tessellate_shape(mc, linear_deflection=0.2).vertices)
    c0 = v.mean(0)
    u_mc = np.linalg.svd(v - c0)[2][0]
    u_mc = u_mc if u_mc @ (mcp - c0) > 0 else -u_mc
    u_mc -= a * (u_mc @ a)
    u_mc /= np.linalg.norm(u_mc)
    n_mc = np.cross(a, u_mc)
    n_mc = n_mc if n_mc @ palmar > 0 else -n_mc
    frames = {"PP": (mcp, u, palmar), "MP": (pip, u, palmar), "MC": (mcp, -u_mc, n_mc)}
    lengths = {"PP": PIN_Y, "MP": DIP_FROM_PIP}
    env = G.section_envelopes(frames, {"PP": pp, "MP": mp, "MC": mc}, {**lengths, "DP": 1.0}, a)

    def stations(shape, p0, uu, lo, hi):
        out = []
        for c in G.cylinders(shape, G.PIN_R):
            s = float((c[0] - p0) @ uu)
            if abs((c[0] - p0) @ a) < 8.0 and lo <= s <= hi:
                out.append(round(s, 3))
        return sorted(set(out))
    holes = {"MC": stations(mc, mcp, -u_mc, 3, 80),
             "PP": [s for s in stations(pp, mcp, u, 0, PIN_Y) if 3 < s < PIN_Y - 3],
             "MP": [s for s in stations(mp, pip, u, 0, DIP_FROM_PIP) if 3 < s < DIP_FROM_PIP - 3]}

    # stand-in DP: the old index DP, scaled
    old = json.loads(OLD.read_text())["fingers"]["Index"]
    k_len = DIP_FROM_PIP / old["link_lengths"]["MP"]
    k_dep = max(env["MP"]["palmar"]) / max(old["section_envelope"]["MP"]["palmar"])
    od = old["section_envelope"]["DP"]
    env["DP"] = {"s": [round(s * k_len, 3) for s in od["s"]],
                 "palmar": [round(p * k_dep, 3) for p in od["palmar"]],
                 "dorsal": [round(p * k_dep, 3) for p in od["dorsal"]]}
    lengths["DP"] = round(old["link_lengths"]["DP"] * k_len, 3)
    holes["DP"] = [round(s * k_len, 3) for s in old["hole_stations"]["DP"]]

    # flexion stops from the parts: MCP (PP against MC2), PIP (MP against the PP)
    flex = np.array([-1.0, 0.0, 0.0])          # +Y towards -Z
    pp_upper = max(pps, key=lambda s: float(np.asarray(tessellate_shape(s, linear_deflection=0.3).vertices)[:, 1].max()))
    pts = lambda s: np.asarray(tessellate_shape(s, linear_deflection=0.08).vertices)  # noqa: E731
    rom = {"MCP": G.flexion_stop(mc, pts(pp), mcp, flex),
           "PIP": G.flexion_stop(pp_upper, pts(mp), pip, flex),
           "DIP": T.ANATOMICAL_MAX_DEG["DIP"]}
    rest_mcp = float(np.degrees(np.arctan2(u @ n_mc, u @ u_mc)))
    geo = {"mcp_centre": mcp.tolist(), "mcp_ball_radius": fr["ball_r"], "pip_axis_point": pip.tolist(),
           "dip_axis_point": dip.tolist(), "lateral_axis": a.tolist(), "palmar_sign": 1.0,
           "pin_axes_parallel_deg": 0.0, "link_lengths": {k: round(v, 3) for k, v in lengths.items()},
           "rest_angles_deg": {"MCP": round(rest_mcp, 2), "PIP": 0.0, "DIP": 0.0},
           "rom_from_rest_deg": {k: (round(v, 1) if v is not None else T.ANATOMICAL_MAX_DEG[k])
                                 for k, v in rom.items()},
           "hole_stations": holes, "section_envelope": env,
           "stand_in_dp": {"source": "old index DP (results/tendon_routing/type_a_geometry.json)",
                           "length_scale": round(k_len, 4), "depth_scale": round(k_dep, 4)}}
    return {"source": "iteration3_hand_assembly.step + stand-in DP", "units": "mm, deg",
            "frame": "A8 study frame (iteration3_frame.py), MP straightened", "fingers": {"Index": geo}}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = geometry()
    gpath = OUT / "type_a_geometry.json"
    gpath.write_text(json.dumps(data, indent=1))
    g = data["fingers"]["Index"]
    print("links", g["link_lengths"], "rest", g["rest_angles_deg"], "rom", g["rom_from_rest_deg"])
    print("holes", g["hole_stations"])
    print("palmar depth max", {k: max(v["palmar"]) for k, v in g["section_envelope"].items()})
    # The MC2 socket wraps the MCP ball to 6 mm past its centre on both sides, so the
    # proximal phalanx's neck meets its rim at about 39 deg of flexion. Run as drawn, and
    # with the socket relieved so the MCP reaches its anatomical 90 deg.
    relieved = json.loads(json.dumps(data))
    rg = relieved["fingers"]["Index"]
    rg["rom_from_rest_deg"]["MCP"] = round(T.ANATOMICAL_MAX_DEG["MCP"] - rg["rest_angles_deg"]["MCP"], 2)
    rpath = OUT / "type_a_geometry_mcp_relieved.json"
    rpath.write_text(json.dumps(relieved, indent=1))
    T.PIN_HEAD_RADIUS_MM = {"PIP": JOINT_HEAD_R, "DIP": JOINT_HEAD_R}
    summary = {}
    for variant, path in (("as_drawn", gpath), ("mcp_relieved", rpath)):
        for spring, k in SPRINGS.items():
            T.OUT = OUT / variant / spring
            T.OUT.mkdir(parents=True, exist_ok=True)
            T.TYPE_A_COVER_K_NM_PER_RAD = k
            for scenario in T.SCENARIOS:
                rows = T.run_type_a(path, scenario)
                summary[f"{variant}_{spring}_{scenario}"] = rows
                for r in rows:
                    print(variant, spring, scenario, r["joint"], "fingertip", r["holdable_fingertip_force_N"],
                          "N; guides", r["guide_on_proximal_mm_from_pivot"], r["guide_on_distal_mm_from_pivot"],
                          "offset", r["palmar_offset_from_centreline_mm"], "excursion", r["excursion_mm"])
    summary["_spring_modulus_mpa"] = E_SPRING_MPA
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
