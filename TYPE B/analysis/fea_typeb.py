"""
Nonlinear FEA of one Type B joint: a full flexion sweep plus three small off-axis
load cases, on the TPU flex zone of a variant (collar + flexure + collar).

How the joint is loaded, and why
--------------------------------

The flexure is attached where the A3 fit check attaches its strap: through rigid
collars on each phalanx. Here the collars are the 0.8 mm shoulders that sit
against the phalanx end faces (the tabs behind them are held inside the PLA
sockets), so:

* every node in the proximal collar is fixed;
* every node in the distal collar is tied into one rigid body;
* the rigid body is rotated about the joint's lateral (X) axis, 0 deg up to the
  joint's target flexion, with its translations FREE.

Free translations are the difference from the repo's A3 stiffness study, and
deliberate. The A3 strap is a spring beside a pinned hinge, so its distal
collar has to rotate about the pin. A Type B joint has no pin; the TPU itself
is the joint, and it rotates about whatever centre its own shape gives it.
Pinning that centre would impose an axis the part does not have and load it
axially. Free translations with a prescribed rotation is a pure bending moment
applied under displacement control: stable, and it lets the joint find its own
centre, which is then reported as a result ("axis drift").

Three linear load cases follow on the same mesh, to measure what a flexure
should resist: twist about the finger axis, sideways bending, and axial
compression from the tendon.

Material: the repo's provisional Neo-Hookean TPU (E = 12 MPa, nu = 0.4995).
Under displacement control the strains and the joint's motion do not depend on
E at all for a Neo-Hookean solid at these strains (both scale out), so every
geometric conclusion here holds whatever the real modulus turns out to be.
Moments and stresses scale linearly with E and are quoted at 12 MPa.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TYPEB = HERE.parent
REPO = TYPEB.parent
sys.path.insert(0, str(TYPEB))
sys.path.insert(0, str(REPO / "src"))

import cadquery as cq  # noqa: E402
import build_finger_type_b as B  # noqa: E402
import build_flexure_families as FF  # noqa: E402
from barnes_ui.core.fea.meshing import MeshSettings, generate_mesh  # noqa: E402
from barnes_ui.core.fea import deck as repo_deck  # noqa: E402
from barnes_ui.core.material.models import provisional_tpu  # noqa: E402
import barnes_ui.core.cad.export as _repo_export  # noqa: E402


def _write_brep(shape, path):
    # The repo's writer goes through an OCP wrapper built for a different OCP
    # release than CadQuery 2.8 ships; the file it writes is the same.
    cq.Shape.cast(shape).exportBrep(str(path))
    return Path(path)


_repo_export.write_brep = _write_brep

E_MPA = 12.0
TARGET_DEG = {"MCP": 90.0, "PIP": 100.0, "DIP": 80.0}
LATTICE_ELEMENTS_THROUGH = 1.5   # see the mesh check in the report
FIELD_EVERY = 3           # increments between strain/stress field snapshots
ROOT_EXCLUSION = 0.4      # mm: peak metrics ignore the sharp collar/flexure corner
CS = {"MCP": B.CS_MCP, "PIP": B.CS_PIP, "DIP": B.CS_DIP}
BASE_SPEC = {"MCP": B.MCP, "PIP": B.PIP, "DIP": B.DIP}


# ---------------------------------------------------------------------------
# VARIANTS
# ---------------------------------------------------------------------------
def all_variants():
    """name -> dict(family, flexure, spec_for(joint), min_feature(joint))"""
    out = {}
    for name, cfg in B.VARIANTS.items():
        specs = dict(zip(("MCP", "PIP", "DIP"), B.variant_specs(cfg["t_scale"], cfg["crossings"])))
        out[name] = dict(family="B_lattice", params=dict(cfg), flexure=None,
                         spec=lambda j, s=specs: s[j],
                         min_feature=lambda j, s=specs: s[j]["pal_t"])
    for key, fam in FF.FAMILIES.items():
        for name, (params, fx) in fam["variants"].items():
            t = params.get("t", params.get("throat"))
            out[name] = dict(family=fam["folder"], params=dict(params), flexure=fx,
                             spec=lambda j: BASE_SPEC[j],
                             min_feature=lambda j, t=t: t * FF.GRADE[j])
    return out


def min_feature(variant, joint, info):
    """Thinnest dimension of the flexure: thickness, or width when narrower."""
    if variant["flexure"] is None:
        return min(info["palmar"]["t"], info["palmar"]["x_t"], info["dorsal"]["t"])
    vals = [info["t"]] + ([info["w"]] if "w" in info else [])
    return min(vals)


def flex_zone(variant, joint):
    """The FEA body: proximal collar, flexure, distal collar. Returns
    (solid, info, z_flex, flex_len)."""
    cs, spec = CS[joint], variant["spec"](joint)
    c, F = B.COLLAR_LEN, spec["flex_len"]
    cw, ch, cr = B.collar_dims(cs)
    fx = variant["flexure"] or B.lattice_flexure
    parts, info = fx(cs, spec, c, F, f"{joint} fea")
    solid = B.fuse([B.prism(cw, ch, cr, 0, c)] + parts + [B.prism(cw, ch, cr, c + F, c)])
    return solid, info, c, F


# ---------------------------------------------------------------------------
# DECKS
# ---------------------------------------------------------------------------
def _lines():
    buf = []
    return buf, buf.append


def _common(out, mesh, material, prox, dist, ref_xyz):
    n = mesh.node_count
    out("*NODE, NSET=Nall")
    for i, (x, y, z) in enumerate(mesh.nodes, start=1):
        out(f"{i}, {x:.6f}, {y:.6f}, {z:.6f}")
    ref, rot = n + 1, n + 2
    out(f"{ref}, {ref_xyz[0]:.6f}, {ref_xyz[1]:.6f}, {ref_xyz[2]:.6f}")
    out(f"{rot}, {ref_xyz[0]:.6f}, {ref_xyz[1]:.6f}, {ref_xyz[2]:.6f}")
    repo_deck._write_elements(out, mesh)
    for name, ids in (("PROX", prox), ("DIST", dist)):
        out(f"*NSET, NSET={name}")
        ids = [int(i) + 1 for i in ids]
        for k in range(0, len(ids), 12):
            out(", ".join(str(i) for i in ids[k:k + 12]) + ",")
    out(f"*NSET, NSET=REF\n{ref},")
    out(f"*NSET, NSET=ROT\n{rot},")
    out(f"*RIGID BODY, NSET=DIST, REF NODE={ref}, ROT NODE={rot}")
    repo_deck._write_material(out, material)
    out("*SOLID SECTION, ELSET=Eall, MATERIAL=TPU")
    return ref, rot


def flexion_deck(mesh, material, prox, dist, ref_xyz, target_deg, pin_ref=False, first_inc=0.01):
    buf, out = _lines()
    out("** Type B joint flexion sweep: pure moment under rotation control")
    _common(out, mesh, material, prox, dist, ref_xyz)
    out("*STEP, NLGEOM, INC=2000")
    out("*STATIC")
    out(f"{first_inc}, 1.0, 1e-6, 0.025")
    out("*BOUNDARY")
    out("PROX, 1, 3, 0.0")
    if pin_ref:
        out("REF, 1, 3, 0.0")      # pinned hinge (A3 benchmark: the strap is a spring beside a pin)
    else:
        out("REF, 1, 1, 0.0")      # no sideways (X) drift; the part is symmetric in X
    out("ROT, 2, 3, 0.0")          # no twist, no sideways bend
    out(f"ROT, 1, 1, {math.radians(target_deg):.9f}")
    # moment and pose at every increment; fields every FIELD_EVERY increments
    out("*NODE PRINT, NSET=ROT, TOTALS=NO, FREQUENCY=1\nRF")
    out("*NODE PRINT, NSET=REF, FREQUENCY=1\nU")
    out(f"*NODE FILE, FREQUENCY={FIELD_EVERY}\nU")
    out(f"*EL FILE, FREQUENCY={FIELD_EVERY}\nS, E")
    out("*END STEP")
    return "\n".join(buf) + "\n"


def offaxis_deck(mesh, material, prox, dist, ref_xyz):
    """Three small linear steps, each resetting the boundary conditions."""
    buf, out = _lines()
    out("** Type B joint off-axis stiffness: torsion, lateral bend, axial")
    _common(out, mesh, material, prox, dist, ref_xyz)
    small = math.radians(1.0)
    cases = [
        ("torsion about the finger axis (Z), 1 deg", ["ROT, 1, 2, 0.0", f"ROT, 3, 3, {small:.9f}"]),
        ("lateral bend about Y, 1 deg", ["ROT, 1, 1, 0.0", "ROT, 3, 3, 0.0", f"ROT, 2, 2, {small:.9f}"]),
        ("axial compression 0.02 mm", ["ROT, 1, 3, 0.0", "REF, 3, 3, -0.02"]),
    ]
    for title, bcs in cases:
        out(f"** {title}")
        out("*STEP")
        out("*STATIC")
        out("*BOUNDARY, OP=NEW")
        out("PROX, 1, 3, 0.0")
        for b in bcs:
            out(b)
        out("*NODE PRINT, NSET=ROT, TOTALS=NO\nRF")
        out("*NODE PRINT, NSET=REF, TOTALS=NO\nRF")
        out("*END STEP")
    return "\n".join(buf) + "\n"


# ---------------------------------------------------------------------------
# RESULT PARSING
# ---------------------------------------------------------------------------
_BLOCK = re.compile(r"^\s*(forces|displacements) \(\w+,\w+,\w+\) for set (\w+) and time\s+([0-9.Ee+-]+)")


def parse_dat(path):
    """{(kind, set): [(time, (a, b, c)), ...]} for single-node sets."""
    hist = {}
    lines = Path(path).read_text().splitlines()
    i = 0
    while i < len(lines):
        m = _BLOCK.match(lines[i])
        if m:
            kind, sset, t = m.group(1), m.group(2), float(m.group(3))
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            vals = [float(v) for v in lines[j].split()[1:4]]
            hist.setdefault((kind, sset.upper()), []).append((t, vals))
            i = j
        i += 1
    return hist


def parse_frd(path, n_nodes):
    """Frames of nodal U (n,3), S (n,6), E (n,6), keyed by step time."""
    frames, cur_t = {}, None
    block, rows = None, None
    with open(path) as f:
        for line in f:
            if line.startswith("  100C"):
                cur_t = float(line[12:24])
                frames.setdefault(cur_t, {})
            elif line.startswith(" -4"):
                block = line.split()[1]
                ncomp = {"DISP": 3, "STRESS": 6, "TOSTRAIN": 6}.get(block)
                if ncomp is None:
                    block = None
                else:
                    rows = np.full((n_nodes, ncomp), np.nan)
            elif line.startswith(" -1") and block is not None:
                node = int(line[3:13])
                if node <= n_nodes:
                    vals = [float(line[13 + 12 * k:25 + 12 * k]) for k in range(rows.shape[1])]
                    rows[node - 1] = vals
            elif line.startswith(" -3") and block is not None:
                frames[cur_t][block] = rows
                block = None
    return frames


def principal(tensor6):
    """xx yy zz xy yz zx (tensor shear) -> sorted eigenvalues (n,3)."""
    t = tensor6
    m = np.empty((t.shape[0], 3, 3))
    m[:, 0, 0], m[:, 1, 1], m[:, 2, 2] = t[:, 0], t[:, 1], t[:, 2]
    m[:, 0, 1] = m[:, 1, 0] = t[:, 3]
    m[:, 1, 2] = m[:, 2, 1] = t[:, 4]
    m[:, 0, 2] = m[:, 2, 0] = t[:, 5]
    return np.linalg.eigvalsh(m)


def von_mises(s):
    return np.sqrt(0.5 * ((s[:, 0] - s[:, 1]) ** 2 + (s[:, 1] - s[:, 2]) ** 2 + (s[:, 2] - s[:, 0]) ** 2)
                   + 3 * (s[:, 3] ** 2 + s[:, 4] ** 2 + s[:, 5] ** 2))


def surface_nodes(elements):
    faces = {}
    for el in elements[:, :4]:
        for f in ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)):
            key = tuple(sorted(int(el[k]) for k in f))
            faces[key] = faces.get(key, 0) + 1
    return np.unique([n for k, v in faces.items() if v == 1 for n in k])


def rot_x(theta):
    c, s = math.cos(theta), math.sin(theta)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


# ---------------------------------------------------------------------------
# COLLISION OF THE RIGID PARTS (collars + phalanges) ALONG THE FEA MOTION
# ---------------------------------------------------------------------------
_PHAL = {"PIP": ("02_Phalanx1", "04_Phalanx2"), "DIP": ("04_Phalanx2", "06_Phalanx3"),
         "MCP": (None, "02_Phalanx1")}
_PHAL_CACHE = {}


def _phalanx(name):
    if name not in _PHAL_CACHE:
        _PHAL_CACHE[name] = cq.importers.importStep(str(TYPEB / "common_phalanges" / f"{name}.step")).val()
    return _PHAL_CACHE[name]


def rigid_sets(joint, c, F):
    """Proximal (fixed) and distal (moving) rigid geometry in flex-zone coordinates:
    collars plus the phalanges whose end faces they seat against."""
    cw, ch, cr = B.collar_dims(CS[joint])
    prox = [B.prism(cw, ch, cr, 0, c)]
    dist = [B.prism(cw, ch, cr, c + F, c)]
    pn, dn = _PHAL[joint]
    lengths = {"02_Phalanx1": B.L_PHAL1 - 2 * B.COLLAR_LEN, "04_Phalanx2": B.L_PHAL2 - 2 * B.COLLAR_LEN,
               "06_Phalanx3": B.L_PHAL3 - B.COLLAR_LEN}
    if pn is not None:
        prox.append(_phalanx(pn).translate(cq.Vector(0, 0, -lengths[pn])))
    else:
        f = B.FLANGE
        prox.append(B._box(-f["w"] / 2, f["w"] / 2, -f["h"] / 2, f["h"] / 2, -f["t"], 0))
    dist.append(_phalanx(dn).translate(cq.Vector(0, 0, 2 * c + F)))
    return B.fuse(prox), B.fuse(dist)


def place(shape, theta, pivot, shift):
    """Rotate about X through pivot by theta, then translate by shift."""
    loc = cq.Location(cq.Vector(*pivot)) * cq.Location(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), math.degrees(theta)) \
        * cq.Location(cq.Vector(*(-np.asarray(pivot))))
    return shape.moved(loc).translate(cq.Vector(*shift))


CLASH_TOL = 0.02   # mm^3


def collision_angle(joint, c, F, ures, target, ref_xyz):
    """First angle at which the rigid parts touch, following the FEA's own pose
    history (rotation plus the free translation of the distal collar)."""
    if not ures:
        return dict(angle=None, first_contact="no pose history")
    p_rigid, d_rigid = rigid_sets(joint, c, F)
    cw, ch, cr = B.collar_dims(CS[joint])
    pc, dc = B.prism(cw, ch, cr, 0, c), B.prism(cw, ch, cr, c + F, c)
    ang = np.array([0.0] + [h[0] * target for h in ures])
    uy = np.array([0.0] + [h[1][1] for h in ures])
    uz = np.array([0.0] + [h[1][2] for h in ures])

    def clash(a):
        y, zz = np.interp(a, ang, uy), np.interp(a, ang, uz)
        return p_rigid.intersect(place(d_rigid, math.radians(a), ref_xyz, (0, y, zz))).Volume()

    prev = 0.0
    for a in ang[1:]:
        if clash(a) > CLASH_TOL:
            lo, hi = prev, a
            for _ in range(7):
                mid = (lo + hi) / 2
                if clash(mid) > CLASH_TOL:
                    hi = mid
                else:
                    lo = mid
            y, zz = np.interp(hi, ang, uy), np.interp(hi, ang, uz)
            cc = pc.intersect(place(dc, math.radians(hi + 1.0), ref_xyz, (0, y, zz))).Volume()
            what = "collar edges" if cc > CLASH_TOL else "phalanx ends / hard-stop nub"
            return dict(angle=float(hi), first_contact=what)
        prev = a
    return dict(angle=None, first_contact=f"none up to {ang[-1]:.1f} deg")


# ---------------------------------------------------------------------------
# ONE RUN
# ---------------------------------------------------------------------------
def run_joint(name, joint, workdir, elements_through=2, keep=False, ccx="ccx", threads=1):
    variants = all_variants()
    v = variants[name]
    started = time.time()
    solid, info, c, F = flex_zone(v, joint)
    is_lattice = v["flexure"] is None
    tmin = min_feature(v, joint, info)
    if is_lattice and elements_through == 2:
        elements_through = LATTICE_ELEMENTS_THROUGH
    size = max(0.2, tmin / elements_through)
    eps = 1e-4
    ref_xyz = (0.0, 0.0, c + F)
    material = provisional_tpu(E_MPA)
    target = TARGET_DEG[joint]

    def mesh_sets(shape, h):
        m = generate_mesh(shape.wrapped, MeshSettings(element_size=h, second_order=True),
                          smallest_dimension=h)
        zz = m.nodes[:, 2]
        return m, np.where(zz <= c + eps)[0], np.where(zz >= c + F - eps)[0]

    if is_lattice:
        # The collars are rigid, so the four lattice columns are independent
        # springs in parallel between the same two rigid bodies, and identical in
        # the YZ plane. One column (palmar + dorsal, inner pair at x > 0) carries
        # exactly a quarter of the flexion moment with the same strains and the
        # same motion. The off-axis cases depend on where the columns sit, so they
        # run on the whole lattice with a coarser mesh.
        x0 = B.CHAN_TENDON_D / 2 + B.TENDON_CLEARANCE
        column = solid.intersect(B._box(x0 - 0.25, x0 + 1.45, -20, 20, -1, c + F + c + 1))
        mesh, prox, dist = mesh_sets(column, size)
        moment_scale = 4.0
        mesh_off, prox_off, dist_off = mesh_sets(solid, max(size, 0.45))
    else:
        mesh, prox, dist = mesh_sets(solid, size)
        moment_scale = 1.0
        mesh_off, prox_off, dist_off = mesh, prox, dist
    z = mesh.nodes[:, 2]

    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    (work / "flex.inp").write_text(flexion_deck(mesh, material, prox, dist, ref_xyz, target,
                                                first_inc=0.0025 if is_lattice else 0.01))
    (work / "offaxis.inp").write_text(offaxis_deck(mesh_off, material, prox_off, dist_off, ref_xyz))
    env = dict(os.environ, OMP_NUM_THREADS=str(threads), CCX_NPROC_EQUATION_SOLVER=str(threads))
    logs = {}
    for job in ("flex", "offaxis"):
        p = subprocess.run([ccx, job], cwd=work, env=env, capture_output=True, text=True, timeout=6 * 3600)
        logs[job] = p.stdout[-3000:]
        (work / f"{job}.log").write_text(p.stdout + p.stderr)

    res = dict(variant=name, joint=joint, family=v["family"], params=v["params"],
               target_deg=target, element_size=size, elements=int(mesh.element_count),
               nodes=int(mesh.node_count), info={k: (list(x) if isinstance(x, tuple) else x)
                                                 for k, x in info.items() if not isinstance(x, dict)})

    # ---- flexion history
    hist = parse_dat(work / "flex.dat") if (work / "flex.dat").exists() else {}
    mom = hist.get(("forces", "ROT"), [])
    ures = hist.get(("displacements", "REF"), [])
    res["completed_fraction"] = mom[-1][0] if mom else 0.0
    res["converged_full"] = bool(mom) and mom[-1][0] > 0.999
    res["moment_scale"] = moment_scale
    res["model"] = "one lattice column x4" if is_lattice else "whole flex zone"
    res["curve"] = [dict(angle=t * target, moment=m[0] * moment_scale) for t, m in mom]
    res["ref_disp"] = [dict(angle=t * target, uy=u[1], uz=u[2]) for t, u in ures]

    # ---- fields at each 10 deg
    frames = []
    if (work / "flex.frd").exists():
        fr = parse_frd(work / "flex.frd", mesh.node_count)
        flex_nodes = np.where((z > c + ROOT_EXCLUSION) & (z < c + F - ROOT_EXCLUSION))[0]
        surf = surface_nodes(mesh.elements)
        surf_set = surf[(z[surf] > c + 0.05) & (z[surf] < c + F - 0.05)]
        from scipy.spatial import cKDTree
        for t in sorted(fr):
            d = fr[t]
            if "TOSTRAIN" not in d or "STRESS" not in d:
                continue
            ang = t * target
            E = d["TOSTRAIN"][flex_nodes]
            S = d["STRESS"][flex_nodes]
            ok = ~np.isnan(E).any(axis=1)
            lam = principal(E[ok])
            stretch_max = np.sqrt(np.clip(1 + 2 * lam[:, 2], 1e-9, None)) - 1
            stretch_min = np.sqrt(np.clip(1 + 2 * lam[:, 0], 1e-9, None)) - 1
            vm = von_mises(S[ok])
            # self-contact proxy: surface points far apart originally that come within 0.1 mm
            U = d["DISP"]
            pos0 = mesh.nodes[surf_set]
            pos = pos0 + U[surf_set]
            tree = cKDTree(pos)
            pairs = tree.query_pairs(0.10, output_type="ndarray")
            contact = 0
            if len(pairs):
                sep0 = np.linalg.norm(pos0[pairs[:, 0]] - pos0[pairs[:, 1]], axis=1)
                contact = int((sep0 > 1.5).sum())
            # rigid pose from the reference node
            uref = np.interp(t, [h[0] for h in ures], [h[1][1] for h in ures]) if ures else 0.0
            wref = np.interp(t, [h[0] for h in ures], [h[1][2] for h in ures]) if ures else 0.0
            theta = math.radians(ang)
            # instantaneous centre of rotation in the YZ plane
            # u = (R - I)(p0 - C)  =>  C = p0 - (R - I)^-1 u
            Rm = rot_x(theta)[1:, 1:]
            p0 = np.array(ref_xyz[1:])
            ctr = p0 - np.linalg.solve(Rm - np.eye(2), np.array([uref, wref]))
            frames.append(dict(angle=ang, strain_max=float(stretch_max.max()),
                               strain_p99=float(np.percentile(stretch_max, 99.5)),
                               strain_min=float(stretch_min.min()), vm_max=float(vm.max()),
                               vm_p99=float(np.percentile(vm, 99.5)), self_contact_pairs=contact,
                               centre_y=float(ctr[0]), centre_z=float(ctr[1])))
    res["frames"] = frames
    res["collision"] = collision_angle(joint, c, F, ures, target, ref_xyz)

    # ---- off-axis
    off = parse_dat(work / "offaxis.dat") if (work / "offaxis.dat").exists() else {}
    rot_rf = off.get(("forces", "ROT"), [])
    ref_rf = off.get(("forces", "REF"), [])
    small = math.radians(1.0)
    if len(rot_rf) >= 3 and len(ref_rf) >= 3:
        res["k_torsion"] = abs(rot_rf[0][1][2]) / small
        res["k_lateral"] = abs(rot_rf[1][1][1]) / small
        res["k_axial"] = abs(ref_rf[2][1][2]) / 0.02
    res["wall_s"] = round(time.time() - started, 1)
    res["ccx_tail"] = {k: v[-600:] for k, v in logs.items()}
    if not keep:
        for f in ("flex.frd", "offaxis.frd", "flex.inp", "offaxis.inp"):
            try:
                (work / f).unlink()
            except FileNotFoundError:
                pass
    return res


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("variant")
    ap.add_argument("joint", choices=["MCP", "PIP", "DIP"])
    ap.add_argument("--work", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--elements-through", type=float, default=2)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--threads", type=int, default=1)
    a = ap.parse_args()
    work = a.work or tempfile.mkdtemp(prefix=f"fea_{a.variant}_{a.joint}_")
    r = run_joint(a.variant, a.joint, work, a.elements_through, a.keep, threads=a.threads)
    txt = json.dumps(r, indent=1)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(txt)
    print(json.dumps({k: r[k] for k in r if k not in ("curve", "ref_disp", "frames", "ccx_tail")}, indent=1))
    for f in r["frames"]:
        print(f)
