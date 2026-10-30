"""Measure the Type A hand assembly for the tendon-routing analysis.

Reads ``reference_parts/type_a_hand_assembly.step`` -- the SolidWorks export of the
whole Type A hand: palm, and the PP/MP/DP of every finger, each phalanx drilled with a
row of prototyping holes -- and writes, per finger, everything the routing analysis
needs, in that finger's own joint frames:

* **Pivots.** MCP: the centre of the palm's spherical socket (each MCP is a ball
  joint, the PP's head a sphere of about 5.3 mm radius). PIP and DIP: the axis of the
  3.2 mm pin bore shared by the two phalanges.
* **Link lengths**, pivot to pivot, and pivot to fingertip for the DP.
* **Hole stations**: where along each link (and along the metacarpal, for the MCP)
  the existing 3.2 mm prototyping holes sit, measured from the joint they serve.
* **Section envelope**: how far the outer surface lies on the palmar and dorsal side
  of the link axis, at stations along every link, found by casting rays from the axis.
  This bounds how far below the centreline a tendon guide can sit before it stands
  proud of the finger.
* **Range of motion**: the flexion angle at which the distal part first runs into the
  proximal one, found by rotating the distal part's surface points about the pin and
  classifying them against the proximal solid. Point sampling can miss a sliver of
  overlap, so these are upper bounds on the true stop, good to a degree or so.

Frames. For each finger, the lateral axis ``a`` is the PIP pin direction. Each link's
axis ``u`` runs from its proximal pivot to its distal one. The palmar direction is
``n = a x u`` signed so that the distal phalanx's resting curl is towards +n -- a
finger at rest is flexed, never hyper-extended.

Usage::

    python scripts/type_a_geometry.py

Needs the OpenCASCADE bindings (``pip install cadquery-ocp``).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from OCP.BRepAdaptor import BRepAdaptor_Surface  # noqa: E402
from OCP.BRepClass3d import BRepClass3d_SolidClassifier  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Sphere  # noqa: E402
from OCP.gp import gp_Dir, gp_Lin, gp_Pnt  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector  # noqa: E402
from OCP.TopAbs import TopAbs_FACE, TopAbs_IN  # noqa: E402
from OCP.TopExp import TopExp_Explorer  # noqa: E402
from OCP.TopoDS import TopoDS  # noqa: E402

from barnes_ui.core.assembly.loader import load_step_assembly  # noqa: E402
from barnes_ui.core.cad.tessellate import tessellate_shape  # noqa: E402

STEP = ROOT / "reference_parts" / "type_a_hand_assembly.step"
OUT = ROOT / "results" / "tendon_routing" / "type_a_geometry.json"
FINGERS = ("Index", "Middle", "Ring", "Little")
PIN_R = 1.6          # 3.2 mm pin and prototyping-hole bores
HOLE_PITCH_TOL = 0.2


def product_names(step_text: str) -> dict[str, str]:
    """Map each NAUO instance id to its SolidWorks part name.

    The XCAF reader names components by instance (NAUO1, NAUO2...); the part names
    live on the PRODUCT entities the usage occurrences point at.
    """
    ent = {int(m.group(1)): m.group(2)
           for m in re.finditer(r"^#(\d+)\s*=\s*(.*?);\s*$", step_text, re.M | re.S)}
    refs = lambda s: [int(x) for x in re.findall(r"#(\d+)", s)]  # noqa: E731
    out = {}
    for v in ent.values():
        if v.startswith("NEXT_ASSEMBLY_USAGE_OCCURRENCE"):
            inst = re.findall(r"'([^']*)'", v)[0]
            pd = ent[refs(v)[1]]
            prod = ent[refs(ent[refs(pd)[0]])[0]]
            out[inst] = re.findall(r"'([^']*)'", prod)[0]
    return out


def faces(shape):
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        yield TopoDS.Face(ex.Current())
        ex.Next()


def _area_centre(face):
    g = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, g)
    c = g.CentreOfMass()
    return g.Mass(), np.array([c.X(), c.Y(), c.Z()])


def cylinders(shape, radius):
    """Coaxial groups of cylindrical faces of one radius: (point, dir, area, centre)."""
    groups: dict[tuple, list] = {}
    for f in faces(shape):
        s = BRepAdaptor_Surface(f)
        if s.GetType() != GeomAbs_Cylinder or abs(s.Cylinder().Radius() - radius) > 0.02:
            continue
        ax = s.Cylinder().Axis()
        d = np.array([ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()])
        d = d if d[np.argmax(abs(d))] > 0 else -d
        p = np.array([ax.Location().X(), ax.Location().Y(), ax.Location().Z()])
        foot = p - d * p.dot(d)
        area, cm = _area_centre(f)
        key = (tuple(np.round(d, 2)), tuple(np.round(foot, 1)))
        groups.setdefault(key, []).append((area, cm, d))
    out = []
    for items in groups.values():
        area = sum(i[0] for i in items)
        cm = sum(i[0] * i[1] for i in items) / area
        out.append((cm, items[0][2], area))
    return out


def spheres(shape):
    out = []
    for f in faces(shape):
        s = BRepAdaptor_Surface(f)
        if s.GetType() == GeomAbs_Sphere:
            p = s.Sphere().Location()
            out.append((np.array([p.X(), p.Y(), p.Z()]), s.Sphere().Radius(),
                        _area_centre(f)[0]))
    return out


def shared_axis(cyl_a, cyl_b, tol=0.3):
    """A pin bore present in both parts: same direction, lines within ``tol`` mm."""
    best = None
    for pa, da, aa in cyl_a:
        for pb, db, ab in cyl_b:
            if abs(abs(da.dot(db)) - 1) > 1e-3:
                continue
            w = pb - pa
            dist = np.linalg.norm(w - da * w.dot(da))
            if dist < tol and (best is None or aa + ab > best[2]):
                best = ((pa + pb) / 2, da, aa + ab)
    return best


def ray_extent(shape, origin, direction, max_len=30.0):
    """Distance from ``origin`` along ``direction`` to the last surface crossing."""
    hit = IntCurvesFace_ShapeIntersector()
    hit.Load(shape, 1e-6)
    hit.Perform(gp_Lin(gp_Pnt(*origin), gp_Dir(*direction)), 0.0, max_len)
    if not hit.IsDone() or hit.NbPnt() == 0:
        return 0.0
    return max(hit.WParameter(i) for i in range(1, hit.NbPnt() + 1))


#: Rays are cast this far either side of the centreline as well as on it, so a
#: station that falls on a 3.2 mm prototyping hole still reads the material beside
#: the hole rather than the empty bore.
LATERAL_PROBES_MM = (-2.0, 0.0, 2.0)


def section_envelopes(frames, shapes, lengths, lateral, n_st=60):
    """Palmar and dorsal depth of each link's surface from its axis, along the link."""
    out = {}
    for key, shape in shapes.items():
        p0, u, n = frames[key]
        length = 45.0 if key == "MC" else lengths[key]
        s_all = np.linspace(0.05 * length, 0.95 * length, n_st)
        pal = [max(ray_extent(shape, p0 + u * s + lateral * y, n) for y in LATERAL_PROBES_MM)
               for s in s_all]
        dor = [max(ray_extent(shape, p0 + u * s + lateral * y, -n) for y in LATERAL_PROBES_MM)
               for s in s_all]
        out[key] = {"s": s_all.round(3).tolist(), "palmar": np.round(pal, 3).tolist(),
                    "dorsal": np.round(dor, 3).tolist()}
    return out


def refresh_envelopes() -> None:
    """Recompute only the section envelopes in an existing geometry file.

    The range-of-motion search dominates the run time (tens of minutes); the
    envelopes take seconds. Frames are rebuilt from the stored pivots.
    """
    data = json.loads(OUT.read_text())
    names = product_names(STEP.read_text(errors="replace"))
    parts = {names[c.name]: c.shape for c in load_step_assembly(STEP).parts()}
    palm = parts["Palm base assembly as part"]
    palm_holes = cylinders(palm, PIN_R)
    for finger, f in data["fingers"].items():
        a = np.array(f["lateral_axis"])
        mcp, pip_p, dip_p = (np.array(f[k]) for k in
                             ("mcp_centre", "pip_axis_point", "dip_axis_point"))
        onto = lambda p: p - a * (p - pip_p) @ a  # noqa: E731
        L = f["link_lengths"]
        u_pp = onto(pip_p) - onto(mcp)
        u_pp /= np.linalg.norm(u_pp)
        u_mp = onto(dip_p) - pip_p
        u_mp /= np.linalg.norm(u_mp)
        dv = np.asarray(tessellate_shape(parts[f"{finger}_DP"],
                                         linear_deflection=0.1).vertices)
        tip = onto(dv[np.argmax(np.linalg.norm(
            (dv - dip_p) - np.outer((dv - dip_p) @ a, a), axis=1))])
        u_dp = tip - onto(dip_p)
        u_dp /= np.linalg.norm(u_dp)
        sign = 1.0 if u_dp @ np.cross(a, u_mp) >= 0 else -1.0
        n_mp = sign * np.cross(a, u_mp)
        frames = {"PP": (onto(mcp), u_pp, sign * np.cross(a, u_pp)),
                  "MP": (pip_p, u_mp, n_mp),
                  "DP": (onto(dip_p), u_dp, sign * np.cross(a, u_dp))}
        row = [h for h in palm_holes if abs((h[0] - mcp) @ a) < 3.0
               and (h[0] - mcp) @ u_pp < -3.0]
        pts = np.array([h[0] for h in row])
        u_mc = np.linalg.svd(pts - pts.mean(0))[2][0]
        u_mc = u_mc if u_mc @ (mcp - pts.mean(0)) > 0 else -u_mc
        u_mc -= a * (u_mc @ a)
        u_mc /= np.linalg.norm(u_mc)
        frames["MC"] = (mcp, -u_mc, sign * np.cross(a, u_mc))
        f["section_envelope"] = section_envelopes(
            frames, {"PP": parts[f"{finger}_PP"], "MP": parts[f"{finger}_MP"],
                     "DP": parts[f"{finger}_DP"], "MC": palm}, L, a)
        print(finger, {k: max(v["palmar"]) for k, v in f["section_envelope"].items()})
    OUT.write_text(json.dumps(data, indent=1))


def rot(axis, angle):
    a = axis / np.linalg.norm(axis)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(angle) * k + (1 - np.cos(angle)) * k @ k


def flexion_stop(proximal, distal_pts, pivot, axis, max_deg=150.0, near=14.0,
                 max_points=400):
    """First flexion angle (deg) at which distal surface points enter the proximal solid.

    Rotating by ``angle`` about ``axis`` through ``pivot`` is flexion. Only points
    within ``near`` mm of the pivot are tested -- a stop is made by the parts around
    the joint -- and points already inside at 0 deg (pin, press fits) are excluded.
    Coarse 5-degree steps, then 0.5-degree steps over the last interval.
    """
    classifier = BRepClass3d_SolidClassifier(proximal)

    def hits(pts):
        n = 0
        for p in pts:
            classifier.Perform(gp_Pnt(*p), 1e-3)
            n += classifier.State() == TopAbs_IN
        return n

    pts = distal_pts[np.linalg.norm(distal_pts - pivot, axis=1) < near]
    if len(pts) > max_points:     # evenly thinned: a stop is a region, not a point
        pts = pts[np.linspace(0, len(pts) - 1, max_points).astype(int)]
    keep = []
    for p in pts:
        classifier.Perform(gp_Pnt(*p), 1e-3)
        keep.append(classifier.State() != TopAbs_IN)
    pts = pts[np.array(keep, bool)]

    def collides(deg):
        moved = (pts - pivot) @ rot(axis, np.radians(deg)).T + pivot
        return hits(moved) >= 3

    lo = 0.0
    for deg in np.arange(5.0, max_deg + 5.0, 5.0):
        if collides(deg):
            for fine in np.arange(lo + 0.5, deg + 0.5, 0.5):
                if collides(fine):
                    return float(fine - 0.5)
            return float(deg)
        lo = deg
    return float(max_deg)


def main() -> None:
    text = STEP.read_text(errors="replace")
    names = product_names(text)
    asm = load_step_assembly(STEP)
    parts = {names[c.name]: c.shape for c in asm.parts()}
    palm = parts["Palm base assembly as part"]
    palm_spheres = spheres(palm)
    palm_holes = cylinders(palm, PIN_R)

    result = {"source": STEP.name, "units": "mm, deg",
              "frame": "per finger: a = PIP pin direction, u = link axis, "
                       "n = palmar (DP rests curled towards +n)",
              "fingers": {}}
    for finger in FINGERS:
        pp, mp, dp = (parts[f"{finger}_{k}"] for k in ("PP", "MP", "DP"))
        pp_c, mp_c, dp_c = (cylinders(s, PIN_R) for s in (pp, mp, dp))
        pip_p, a, _ = shared_axis(pp_c, mp_c)
        dip_p, a_dip, _ = shared_axis(mp_c, dp_c)
        # MCP: the PP's ball head, concentric with a palm socket.
        head = max(spheres(pp), key=lambda s: s[2])
        mcp = head[0]
        socket = min(palm_spheres, key=lambda s: np.linalg.norm(s[0] - mcp))
        assert np.linalg.norm(socket[0] - mcp) < 0.05, finger

        # Project the DIP pin onto the plane through the PIP normal to a.
        def onto_plane(p):
            return p - a * (p - pip_p).dot(a)
        mcp_q, dip_q = onto_plane(mcp), onto_plane(dip_p)

        # Fingertip: the DP mesh point farthest from the DIP axis, in the plane.
        mesh = tessellate_shape(dp, linear_deflection=0.1)
        dv = np.asarray(mesh.vertices)
        tip = onto_plane(dv[np.argmax(np.linalg.norm(
            (dv - dip_p) - np.outer((dv - dip_p) @ a, a), axis=1))])

        links = {"PP": (mcp_q, pip_p), "MP": (pip_p, dip_q), "DP": (dip_q, tip)}
        frames = {}
        for k, (p0, p1) in links.items():
            u = (p1 - p0) / np.linalg.norm(p1 - p0)
            frames[k] = (p0, u, np.cross(a, u))
        # Sign of palmar: the DP's curl relative to the MP axis.
        _, u_mp, n_mp = frames["MP"]
        sign = 1.0 if (frames["DP"][1] @ n_mp) >= 0 else -1.0
        frames = {k: (p0, u, sign * n) for k, (p0, u, n) in frames.items()}
        # Flexion turns the distal link from u towards +n: rotation about sign*a.
        flex_axis = sign * a

        # Metacarpal axis: the line of palm holes behind this MCP (within 3 mm of the
        # finger's mid-plane), fitted and pointed towards the MCP.
        row = [h for h in palm_holes if abs((h[0] - mcp) @ a) < 3.0
               and (h[0] - mcp) @ frames["PP"][1] < -3.0]
        if len(row) >= 2:
            pts = np.array([h[0] for h in row])
            u_mc = np.linalg.svd(pts - pts.mean(0))[2][0]
            u_mc = u_mc if u_mc @ (mcp - pts.mean(0)) > 0 else -u_mc
        else:
            u_mc = frames["PP"][1]
        u_mc = u_mc - a * (u_mc @ a)
        u_mc /= np.linalg.norm(u_mc)
        # MC frame points proximally, away from the MCP, so hole stations are positive.
        frames["MC"] = (mcp, -u_mc, sign * np.cross(a, u_mc))

        def stations(cyls, p0, u, lo, hi):
            out = sorted(float((c[0] - p0) @ u) for c in cyls
                         if abs(abs(c[1] @ a) - 1) > 0.2    # not a pin: crosses the link
                         and abs((c[0] - p0) @ a) < 3.0 and lo <= (c[0] - p0) @ u <= hi)
            return [round(s, 3) for s in out]

        lengths = {k: float(np.linalg.norm(p1 - p0)) for k, (p0, p1) in links.items()}
        holes = {
            "MC": stations(palm_holes, mcp, -u_mc, 3, 80),
            "PP": stations(pp_c, mcp_q, frames["PP"][1], 0, lengths["PP"]),
            "MP": stations(mp_c, pip_p, frames["MP"][1], 0, lengths["MP"]),
            "DP": stations(dp_c, dip_q, frames["DP"][1], 0, lengths["DP"]),
        }

        env = section_envelopes(frames, {"PP": pp, "MP": mp, "DP": dp, "MC": palm},
                                lengths, a)

        # Range of motion from the CAD: rotate the distal part until it hits.
        def surface_pts(shape, step):
            m = tessellate_shape(shape, linear_deflection=0.08)
            return np.asarray(m.vertices)[::step]
        rom = {
            "MCP": flexion_stop(palm, surface_pts(pp, 1), mcp, flex_axis),
            "PIP": flexion_stop(pp, surface_pts(mp, 1), pip_p, flex_axis),
            "DIP": flexion_stop(mp, surface_pts(dp, 1), dip_p, flex_axis),
        }

        def angle(u0, n0, u1):
            """Flexion of link direction u1 relative to u0 (palmar n0 positive)."""
            return round(float(np.degrees(np.arctan2(u1 @ n0, u1 @ u0))), 2)

        result["fingers"][finger] = {
            "mcp_centre": mcp.round(4).tolist(), "mcp_ball_radius": round(head[1], 3),
            "pip_axis_point": pip_p.round(4).tolist(),
            "dip_axis_point": dip_p.round(4).tolist(),
            "lateral_axis": a.round(5).tolist(),
            "palmar_sign": sign,
            "pin_axes_parallel_deg": float(np.degrees(np.arccos(min(1, abs(a @ a_dip))))),
            "link_lengths": {k: round(v, 3) for k, v in lengths.items()},
            "rest_angles_deg": {
                "MCP": angle(u_mc, sign * np.cross(a, u_mc), frames["PP"][1]),
                "PIP": angle(frames["PP"][1], frames["PP"][2], frames["MP"][1]),
                "DIP": angle(frames["MP"][1], frames["MP"][2], frames["DP"][1])},
            "rom_from_rest_deg": rom,
            "hole_stations": holes,
            "section_envelope": env,
        }
        f = result["fingers"][finger]
        print(f"{finger}: L PP/MP/DP = {lengths['PP']:.2f}/{lengths['MP']:.2f}/"
              f"{lengths['DP']:.2f} mm, rest {f['rest_angles_deg']}, ROM {rom}")
        print(f"  holes {holes}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    if "--envelopes-only" in sys.argv:
        refresh_envelopes()
    else:
        main()
