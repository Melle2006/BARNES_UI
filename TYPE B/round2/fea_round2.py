"""
Round-2 tendon-load FEA: does a joint hold the tendon's compression?

Round 1's FEA (../analysis/fea_typeb.py) bends each joint with a pure moment and
leaves its translations free, so nothing ever squeezes the joint along its length.
That is the right test of a spring, but round 2 exists because of the squeeze: the
tendon that bends the joint also pushes the two phalanges together, and docs/11
predicts round 1's leaves buckle under it. TEST_PLAN.md's "compression capacity"
column is a hand estimate (Euler buckling, or 20 % contact strain). This script
replaces it with a nonlinear FEA of the same flex zone round 1 uses.

The load case, at the PIP
-------------------------
Proximal collar fixed; distal collar a rigid body, as in round 1.

1. Bend: the distal body is rotated to the pose angle (0, 30 or 60 deg) with its
   translations free, exactly round 1's flexion step.
2. Squeeze: the rotation is held at the pose and a force of up to ``T_MAX`` is
   ramped onto the distal body along the tendon's line, from where the tendon
   enters the distal collar towards where it leaves the proximal collar. A 1 %
   sideways (Y) push is added so a symmetric joint at 0 deg has a buckling mode to
   find rather than sitting on a bifurcation.

Holding the rotation stands in for the hook load of the TEST_PLAN rig: it supplies
whatever moment keeps the pose. The tendon's own moment about the joint therefore
does not deform anything here; it is booked afterwards, which is why one run serves
a variant and its deep-offset copy when their flexure geometry is the same (every
shortlisted pair except B4, whose rolling radius is set by the offset). The force
direction is the as-built tendon's unless ``--offset deep`` is given; the angle it
makes with the deep tendon's line differs by a few degrees at 60 deg.

Bearings (B4 lobes, B8 knuckle and cup) are 0.3 mm apart as printed. Their curved
faces get a surface-to-surface contact pair, penalty 10 E / h as in the A8 study.

What is reported
----------------
Per load increment: tendon force T, the distal body's translation, the moment the
hold needs, and (every few increments) the peak principal strain away from the
collar roots. ``postprocess`` turns that into a capacity: the tension at which the
first of these happens --

* the solver can no longer find equilibrium (a limit point: buckling or collapse);
* the axial tangent stiffness falls below 10 % of its initial value;
* peak strain reaches 20 %.

Material: the same Neo-Hookean as round 1 at E = 12 MPa. Under a force load every
displacement and strain depends on T / E only, and the contact penalty is set
proportional to E, so a capacity found at 12 MPa scales exactly with E. The
rescaling to the material actually used is done in ../../scripts/sunlu_rescale.py.

    python fea_round2.py B8_y00_r150 --angle 30
    python fea_round2.py B4_t100_a60 --offset deep --angle 60
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TYPEB = HERE.parent
sys.path.insert(0, str(TYPEB / "analysis"))
sys.path.insert(0, str(HERE))

import fea_typeb as R1  # noqa: E402  (also puts the repo and Type B on sys.path)
import build_round2 as R2  # noqa: E402
from barnes_ui.core.fea.contact import _C3D10_FACES  # noqa: E402
from barnes_ui.core.fea import meshing as M  # noqa: E402
from barnes_ui.core.fea.meshing import MeshSettings, generate_mesh  # noqa: E402
from barnes_ui.core.material.models import provisional_tpu  # noqa: E402

JOINT = "PIP"
E_MPA = R1.E_MPA
T_MAX = 150.0            # N of tendon tension at 12 MPa; above every hand estimate
SIDE_PUSH = 0.01         # sideways perturbation, as a fraction of T
CONTACT_TOL = 0.06       # mm: node on a bearing face if within this of its radius
FIELD_EVERY = 4
STRAIN_LIMIT = 0.20
STIFFNESS_DROP = 0.10
AS_BUILT = {j: -y for j, y in {"MCP": -3.06, "PIP": -1.93, "DIP": -1.06}.items()}
DEEP = {j: v[0] for j, v in R2.deepest_offsets().items()}
R2.AS_BUILT.update(AS_BUILT)


def variant(name, offset):
    """A round-1 or round-2 variant as the round-1 driver's variant dict."""
    if name in R1.all_variants():
        return R1.all_variants()[name]
    designs = R2.new_designs(DEEP if offset == "deep" else AS_BUILT)
    params, fx = designs[name]
    return dict(family=params["family"], params=dict(params), flexure=fx,
                spec=lambda j: R1.BASE_SPEC[j], min_feature=None)


def tendon_direction(theta, d, F):
    """Unit (y, z) force on the distal body: from the tendon's distal entry point
    towards its proximal exit, for a joint bending about the flex zone's middle."""
    c = R1.B.COLLAR_LEN
    q = np.array([-d, c])
    ctr = np.array([0.0, c + F / 2])
    p0 = np.array([-d, c + F]) - ctr
    cth, sth = math.cos(theta), math.sin(theta)
    p = ctr + np.array([p0[0] * cth - p0[1] * sth, p0[0] * sth + p0[1] * cth])
    v = q - p
    return v / np.linalg.norm(v), p, q


def boundary_faces(mesh):
    """[(element index, face label, six node ids)] for every free face of the mesh.
    Round 1's surface_nodes() keeps corner nodes only, which is enough for its
    proximity check but not for a contact surface: CalculiX needs whole faces."""
    seen = {}
    for e, conn in enumerate(mesh.elements):
        for label, pos in _C3D10_FACES.items():
            nodes = tuple(int(conn[k]) for k in pos)
            key = tuple(sorted(nodes[:3]))
            seen.setdefault(key, []).append((e, label, nodes))
    return [v[0] for v in seen.values() if len(v) == 1]


def bearing_faces(mesh, info, c, F):
    """(slave faces, master faces) on the two bearing surfaces, or None. A free face
    belongs to a bearing when all six of its nodes lie on that bearing's circle."""
    kind = info.get("bearing")
    if kind not in ("rolling", "knuckle"):
        return None
    y, z = mesh.nodes[:, 1], mesh.nodes[:, 2]
    zm = c + F / 2
    if kind == "knuckle":
        yp, r = info["pivot_y"], info["knuckle_r"]
        rad = np.hypot(y - yp, z - zm)
        on_s = np.abs(rad - r) < CONTACT_TOL
        on_m = np.abs(rad - (r + R2.GAP)) < CONTACT_TOL
    else:
        R = info["roll_r"]
        zp, zd = zm - R2.GAP / 2 - R, zm + R2.GAP / 2 + R
        on_s = (np.abs(np.hypot(y, z - zp) - R) < CONTACT_TOL) & (z > c + 0.05)
        on_m = (np.abs(np.hypot(y, z - zd) - R) < CONTACT_TOL) & (z < c + F - 0.05)
    faces = boundary_faces(mesh)
    slave = [(e, l) for e, l, n in faces if on_s[list(n)].all()]
    master = [(e, l) for e, l, n in faces if on_m[list(n)].all()]
    return slave, master


BEARING_H = 0.5          # mm: bearing lanes (the contact faces are r 1.25-2.1 mm)
COLLAR_H = 0.8           # mm: the collars move rigidly or are fixed


def size_field(v, info, c, F, joint=JOINT):
    """Element size as a function of position, for round-2 joints only.

    Round 2 joints are mostly bulk: a knuckle and cup, two lobes or a stocky web,
    beside a thin return leaf. Meshing all of it at the leaf's two-elements-through
    size gave 30,000-60,000 quadratic tets, and SPOOLES (the only direct solver in
    this CalculiX build) then needed over 12 GB and was killed. So: the leaf or strap
    lane at two elements through its thickness, the B9 neck at three through its
    thickness, the bearing lanes at BEARING_H, the collars at COLLAR_H."""
    cs = R1.CS[joint]
    kind = info.get("bearing")
    t = info["t"]
    if kind == "rolling":
        beta = math.radians(info["angle"] / 2)
        half = F / 2 * math.tan(beta) + t / math.cos(beta) / 2
    else:
        half = t / 2
    inner, outer, _, _ = R2.lanes(cs, half)
    h_spring = t / 2
    zm = c + F / 2

    def f(x, y, z):
        ax = abs(x)
        if z < c - 0.05 or z > c + F + 0.05:
            return COLLAR_H
        if outer[0] - 0.1 <= ax <= outer[1] + 0.1:
            return h_spring
        if kind == "strut" and abs(z - zm) < info["neck_len"] / 2 + 1.0:
            return min(BEARING_H, info["neck_t"] / 3)
        return BEARING_H
    return f, min(h_spring, BEARING_H if kind != "strut" else info["neck_t"] / 3)


def graded_mesh(shape, field, h_min):
    """generate_mesh with a size callback; otherwise the same settings and output."""
    import gmsh
    from barnes_ui.core.cad.export import write_brep
    scratch = Path(tempfile.mkdtemp(prefix="r2_mesh_"))
    write_brep(shape, scratch / "shape.brep")
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("r2")
        gmsh.model.occ.importShapes(str(scratch / "shape.brep"))
        gmsh.model.occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMin", h_min * 0.4)
        gmsh.option.setNumber("Mesh.MeshSizeMax", COLLAR_H)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)
        gmsh.model.mesh.setSizeCallback(lambda dim, tag, x, y, z, lc: min(lc, field(x, y, z)))
        gmsh.model.mesh.generate(3)
        gmsh.model.mesh.setOrder(2)
        nodes, elements = M._extract(gmsh, True)
        surfaces = M._surface_node_sets(gmsh, nodes)
    finally:
        gmsh.finalize()
    mesh = M.Mesh(nodes=nodes, elements=elements, second_order=True, element_size=h_min,
                  node_sets=surfaces)
    mesh.quality = M._quality_metrics(mesh)
    return mesh


def deck(mesh, material, prox, dist, ref_xyz, theta, direction, contact, h, pose_only=False):
    buf, out = R1._lines()
    out(f"** Round-2 tendon load: pose {math.degrees(theta):.1f} deg, then up to {T_MAX} N")
    R1._common(out, mesh, material, prox, dist, ref_xyz)
    if contact is not None:
        for name, faces in contact:
            out(f"*SURFACE, NAME={name}, TYPE=ELEMENT")
            for el, face in faces:
                out(f"{el + 1}, {face}")
        out("*SURFACE INTERACTION, NAME=BEARING")
        out("*SURFACE BEHAVIOR, PRESSURE-OVERCLOSURE=LINEAR")
        out(f"{10.0 * E_MPA / h:.6g}")
        out("*CONTACT PAIR, INTERACTION=BEARING, TYPE=SURFACE TO SURFACE")
        out(f"{contact[0][0]}, {contact[1][0]}")
    ctrl = "*CONTROLS, PARAMETERS=TIME INCREMENTATION\n12, 16, 9, 24, 10, 12"
    out("*STEP, NLGEOM, INC=1000")
    out(ctrl)
    out("*STATIC")
    out("0.05, 1.0, 1e-5, 0.1")
    out("*BOUNDARY")
    out("PROX, 1, 3, 0.0")
    out("REF, 1, 1, 0.0")
    out("ROT, 2, 3, 0.0")
    out(f"ROT, 1, 1, {theta:.9f}")
    out("*NODE PRINT, NSET=ROT, TOTALS=NO\nRF")
    out("*NODE PRINT, NSET=REF\nU")
    out("*END STEP")
    if pose_only:
        return "\n".join(buf) + "\n"
    fy, fz = direction
    out("*STEP, NLGEOM, INC=4000")
    out(ctrl)
    out("*STATIC")
    out("0.0005, 1.0, 1e-5, 0.01")   # 0.075 N first (0.6 N diverged to NaN on a bent leaf); 0.0015 N floor
    out("*CLOAD")
    out(f"REF, 2, {T_MAX * (fy + SIDE_PUSH):.6f}")
    out(f"REF, 3, {T_MAX * fz:.6f}")
    out("*NODE PRINT, NSET=ROT, TOTALS=NO, FREQUENCY=1\nRF")
    out("*NODE PRINT, NSET=REF, FREQUENCY=1\nU")
    out(f"*NODE FILE, FREQUENCY={FIELD_EVERY}\nU")
    out(f"*EL FILE, FREQUENCY={FIELD_EVERY}\nE")
    out("*END STEP")
    return "\n".join(buf) + "\n"


def run(name, angle, offset="as-built", workdir=None, elements_through=2, threads=4, keep=False,
        use_contact=True, pose_only=False):
    started = time.time()
    v = variant(name, offset)
    solid, info, c, F = R1.flex_zone(v, JOINT)
    if v["min_feature"] is not None:
        tmin = R1.min_feature(v, JOINT, info)
    else:
        tmin = min(x for x in (info.get("t"), info.get("neck_t"), info.get("w")) if x)
    h = max(0.2, tmin / elements_through)
    if info.get("bearing"):
        field, h = size_field(v, info, c, F)
        mesh = graded_mesh(solid.wrapped, field, h)
    else:
        mesh = generate_mesh(solid.wrapped, MeshSettings(element_size=h, second_order=True),
                             smallest_dimension=h)
    z = mesh.nodes[:, 2]
    eps = 1e-4
    prox, dist = np.where(z <= c + eps)[0], np.where(z >= c + F - eps)[0]
    ref_xyz = (0.0, 0.0, c + F)
    theta = math.radians(angle)
    d = (DEEP if offset == "deep" else AS_BUILT)[JOINT]
    direction, p_entry, q_exit = tendon_direction(theta, d, F)

    contact = None
    sets = bearing_faces(mesh, info, c, F) if use_contact else None
    if sets is not None:
        slave_f, master_f = sets
        if not slave_f or not master_f:
            raise RuntimeError(f"{name}: bearing faces not found ({len(slave_f)}, {len(master_f)})")
        contact = [("BRG_S", slave_f), ("BRG_M", master_f)]

    work = Path(workdir or tempfile.mkdtemp(prefix=f"r2_{name}_{angle}_"))
    work.mkdir(parents=True, exist_ok=True)
    (work / "job.inp").write_text(deck(mesh, provisional_tpu(E_MPA), prox, dist, ref_xyz,
                                       theta, direction, contact, h, pose_only))
    env = dict(os.environ, OMP_NUM_THREADS=str(threads), CCX_NPROC_EQUATION_SOLVER=str(threads))
    p = subprocess.run(["ccx", "job"], cwd=work, env=env, capture_output=True, text=True,
                       timeout=8 * 3600)
    (work / "job.log").write_text(p.stdout + p.stderr)

    hist = R1.parse_dat(work / "job.dat") if (work / "job.dat").exists() else {}
    mom = hist.get(("forces", "ROT"), [])
    ures = hist.get(("displacements", "REF"), [])
    # step 1 ends at total time 1 (or is absent at 0 deg pose, which still runs it)
    load = [(t - 1.0, m[0], u) for (t, m), (_, u) in zip(mom, ures) if t > 1.0 + 1e-9]
    pose_u = [u for (t, u) in ures if t <= 1.0 + 1e-9]
    u0 = np.array(pose_u[-1]) if pose_u else np.zeros(3)
    pose_moment = [m for (t, m) in mom if t <= 1.0 + 1e-9]
    res = dict(variant=name, offset=offset, joint=JOINT, angle=angle, family=v["family"],
               params=v["params"], E_mpa=E_MPA, T_max=T_MAX, side_push=SIDE_PUSH,
               tendon_offset_mm=d, tendon_dir_yz=list(direction),
               tendon_entry_yz=list(p_entry), tendon_exit_yz=list(q_exit),
               element_size=h, elements=int(mesh.element_count), nodes=int(mesh.node_count),
               contact_faces=None if contact is None else [len(contact[0][1]), len(contact[1][1])],
               info={k: (list(x) if isinstance(x, tuple) else x) for k, x in info.items()
                     if not isinstance(x, dict)},
               pose_reached=bool(pose_moment) or angle == 0.0,
               pose_moment=pose_moment[-1][0] if pose_moment else None,
               pose_ref_u=list(u0))
    res["load"] = []
    for frac, m, u in load:
        du = np.array(u) - u0
        res["load"].append(dict(T=frac * T_MAX, hold_moment=m,
                                du_y=float(du[1]), du_z=float(du[2]),
                                du_along=float(du[1] * direction[0] + du[2] * direction[1])))
    res["load_completed_fraction"] = load[-1][0] if load else 0.0

    frames = []
    if (work / "job.frd").exists():
        fr = R1.parse_frd(work / "job.frd", mesh.node_count)
        flex_nodes = np.where((z > c + R1.ROOT_EXCLUSION) & (z < c + F - R1.ROOT_EXCLUSION))[0]
        for t in sorted(fr):
            if t <= 1.0 + 1e-9 or "TOSTRAIN" not in fr[t]:
                continue
            E = fr[t]["TOSTRAIN"][flex_nodes]
            ok = ~np.isnan(E).any(axis=1)
            lam = R1.principal(E[ok])
            smax = np.sqrt(np.clip(1 + 2 * lam[:, 2], 1e-9, None)) - 1
            smin = np.sqrt(np.clip(1 + 2 * lam[:, 0], 1e-9, None)) - 1
            frames.append(dict(T=(t - 1.0) * T_MAX, strain_max=float(smax.max()),
                               strain_p99=float(np.percentile(smax, 99.5)),
                               strain_min=float(smin.min())))
    res["frames"] = frames
    res["ccx_tail"] = p.stdout[-1500:]
    res["wall_s"] = round(time.time() - started, 1)
    res.update(postprocess(res))
    if not keep:
        for f in ("job.frd", "job.inp"):
            try:
                (work / f).unlink()
            except FileNotFoundError:
                pass
    return res


def postprocess(res):
    """Capacity and what limits it, at the run's own E."""
    load = res["load"]
    if len(load) < 3:
        return dict(capacity_T=0.0 if load or res["load_completed_fraction"] == 0 else None,
                    limited_by="no load increment converged")
    T = np.array([0.0] + [r["T"] for r in load])
    du = np.array([0.0] + [r["du_along"] for r in load])
    k = np.diff(T) / np.maximum(np.diff(du), 1e-12)
    k0 = np.median(k[: max(2, len(k) // 20)])
    cands = []
    if res["load_completed_fraction"] < 0.999:
        cands.append((T[-1], "limit point: no equilibrium beyond this tension (buckling/collapse)"))
    else:
        cands.append((T[-1], f"held the full {res['T_max']:.0f} N"))
    soft = np.where(k < STIFFNESS_DROP * k0)[0]
    # ignore the bearing gap closing: stiffness rising later means it was a gap
    if len(soft):
        i = soft[-1] if k[-1] < STIFFNESS_DROP * k0 else None
        if i is not None:
            j = i
            while j > 0 and k[j - 1] < STIFFNESS_DROP * k0:
                j -= 1
            cands.append((T[j], "axial stiffness fell below 10 % of its initial value"))
    fr = res["frames"]
    over = [f for f in fr if f["strain_max"] >= STRAIN_LIMIT]
    if over:
        prev = [f for f in fr if f["T"] < over[0]["T"]]
        if prev:
            a, b = prev[-1], over[0]
            tcap = a["T"] + (STRAIN_LIMIT - a["strain_max"]) * (b["T"] - a["T"]) / (b["strain_max"] - a["strain_max"])
        else:
            tcap = over[0]["T"]
        cands.append((tcap, "peak strain reached 20 %"))
    cap, why = min(cands, key=lambda x: x[0])
    return dict(capacity_T=float(cap), limited_by=why, axial_k0=float(k0),
                peak_strain_at_cap=float(np.interp(cap, [f["T"] for f in fr], [f["strain_max"] for f in fr]))
                if fr else None)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("variant")
    ap.add_argument("--angle", type=float, default=30.0)
    ap.add_argument("--offset", choices=["as-built", "deep"], default="as-built")
    ap.add_argument("--work")
    ap.add_argument("--out")
    ap.add_argument("--elements-through", type=float, default=2)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--no-contact", action="store_true")
    ap.add_argument("--pose-only", action="store_true")
    a = ap.parse_args()
    r = run(a.variant, a.angle, a.offset, a.work, a.elements_through, a.threads, a.keep,
            not a.no_contact, a.pose_only)
    out = a.out or str(HERE / "fea" / "results" / f"{a.variant}{'_deep' if a.offset == 'deep' else ''}_{a.angle:g}deg.json")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(r, indent=1))
    print(json.dumps({k: r[k] for k in r if k not in ("load", "frames", "ccx_tail", "info")}, indent=1))
