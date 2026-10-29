# TYPE B — TPU lattice-flexure finger

Type B joints are TPU modules whose flex zone is a re-entrant ("bow-tie" or
criss-cross) lattice. Each joint has a compliant palmar lattice and a stiffer
dorsal lattice, built in four columns around a clear central corridor for the
tendon. The modules plug into PLA phalanges.

Everything here comes from `build_finger_type_b.py`, a corrected version of
`build_finger_one_more_lattice_level.py`. Run it again to regenerate all the
files:

```bash
pip install cadquery
```

```bash
python "TYPE B/build_finger_type_b.py"
```

You can also build named variants only, skip the STLs or the assembly, or write
the output somewhere else:

```bash
python "TYPE B/build_finger_type_b.py" B_T110_X3 --no-stl --out /tmp/typeb
```

Each build checks that every part is one valid solid, that adjacent parts in
the assembly don't overlap, and that both retention pins pass clear through
tab and socket at every joint. All variants listed below passed.

## Folder layout

| Path | Contents |
|---|---|
| `build_finger_type_b.py` | The generator: every parameter, variant definition and check |
| `common_phalanges/` | `02_Phalanx1`, `04_Phalanx2` and `06_Phalanx3` as STEP and STL. The phalanges don't depend on the lattice, so the same files are used for every variant. |
| `B00_baseline/` | Your original lattice parameters with the errors corrected, plus `finger_assembly.step` (the full finger, assembled) |
| `B_T###_X#/` | One folder per variant: `01_MCP_module_with_flange`, `03_PIP_module` and `05_DIP_module` as STEP and STL |
| `variants_summary.csv` | Cell count, strut thickness, re-entrant angle, cell height, tendon moment arm and module volume for each joint of each variant |

Assembly STEPs for variants other than the baseline are left out to keep the
repository small. To get one, run
`python "TYPE B/build_finger_type_b.py" <variant>`.

## Variants

Two parameters are varied over a grid:

* **Flexure thickness, `T`.** The in-plane strut thickness, scaled by 0.90,
  1.00, 1.10 or 1.20 (`T090` … `T120`). Every strut is scaled, so the
  palmar:dorsal ratio of 1:2 and the MCP > PIP > DIP grading are both kept.
  Strut bending stiffness goes with t³, so this range spans about 0.73× to
  1.73× the baseline.
* **Criss-crosses, `X`.** The number of bow-tie cells in each palmar lattice:
  2, 3 or 4. Each dorsal lattice gets one fewer, as in the original MCP and
  DIP designs.

`B00_baseline` keeps your original per-joint cell counts (MCP 3/2, PIP 2/2,
DIP 3/2) at T = 1.00. `B_T100_X3` differs from it only at the PIP.

VARIANT_TABLE

The angles are measured at the strut centrelines. The original script measured
the band envelope instead, so its figures were larger.

Why the grid stops where it does:

* Below about 0.90, the DIP palmar strut would be under 0.4 mm, which is
  thinner than a 0.4 mm nozzle can print.
* Above about 1.20, the dorsal DIP and PIP bands are too narrow to stay
  re-entrant. The struts would straighten out to under 0.3 mm of lateral
  travel.

The script refuses to build a variant that breaks either limit and says why.

## Errors corrected

These were found by running the original script and measuring the parts it
exported, which are identical to the reference STEPs you shared.

1. **The phalanx sockets cut away the whole end of each phalanx.** Each socket
   was cut with the phalanx's own outer profile (`rounded_profile(w0, h0)`),
   so nothing was left to form a wall. Phalanx 1 started at z = 4 instead of
   z = 0 and ended in a 0.5 mm² knife edge, so the tabs had nothing to sit in.
   The tab profile also didn't match the socket (r = 2 against r ≈ 5.9), so it
   wouldn't have fitted even with a wall.
   *Fix:* the socket is now the outer profile offset inward by a uniform
   1.2 mm PLA wall. The tab is the socket less 0.3 mm clearance, with a
   matching corner radius. There is 0.3 mm of axial clearance at the floor.
2. **Every "palmar" feature was on the dorsal side.** `Workplane("XZ")` has
   its normal along −Y, so `offset=-h/2` puts the plane at +h/2. This affected
   the hard-stop nubs, both DIP coupling-wire anchor bosses and the fingertip
   sensor recess.
   *Fix:* these features are now built directly at −Y.
3. **Features didn't attach to the body.** The phalanges taper, so their
   surfaces fall away from a nub placed at the end-section height. Phalanx 1
   and Phalanx 2 each exported as two separate solids, with the nub floating.
   The anchor bosses were extruded into the body, so they added nothing, and
   their holes were drilled into empty space on the other side.
   *Fix:* every added feature now starts 0.5 mm inside the local surface. The
   anchor hole goes through the boss and 0.5 mm into the body.
4. **The retention pin holes didn't line up.** The MCP tab pin was at 1.5 mm
   but its socket pin was at 2.5 mm. The PIP pair was at 1.5 and 0.65 mm, and
   the DIP pair at 1.5 and −0.5 mm. The PIP and DIP tabs (2.15 and 1.0 mm
   long) were too short for a Ø2 pin: the PIP hole broke out of its tab, and
   the DIP hole was mostly outside its tab altogether.
   *Fix:* all tabs are now 4.0 mm long, with the pins at mid-tab. The tabs and
   sockets take their pin positions from one shared joint layout. Tabs sit
   inside the sockets, so this doesn't change the visible joint.
5. **The X-direction pin couldn't share a tab with the channels.** It crossed
   at Y = 0 between the tendon and sensor channels, which only worked because
   the tab was oversized. Once the tab is sized for a real socket, there is no
   room for it (at the DIP, the tendon channel and the pin would intersect).
   *Fix:* there are now two Ø2 pins along Y at X = ±x, centred between the
   tendon channel and the tab's side wall.
6. **The tendon channel jumped at every joint.** The modules cut it at
   −pulley_r (−5.0 and −3.5 mm), but the phalanges cut it at a fixed −3.0 mm.
   In the MCP block, a channel at −5 left a 0.2 mm wall.
   *Fix:* the channels are defined once per joint. Each phalanx runs straight
   through its sockets and changes offset with smooth bends in between. The
   offset is capped so at least 0.8 mm of TPU surrounds the channel in the
   tab, giving **effective moment arms of 3.2 / 2.2 / 1.2 mm (MCP / PIP / DIP)
   instead of 5.0 / 3.5 / 3.0**. This is the main functional consequence of
   giving the sockets real walls. A thinner tendon channel would let the arms
   grow (`CHAN_TENDON_D`; 3.0 mm is large for a Dyneema tendon).
7. **The lattice geometry had three defects.**
   * The strut centrelines ended on the band edge, so the struts stuck out of
     their band by t/2.
   * The outer columns overhung the joint block's rounded corners by up to
     0.3 mm.
   * The square-cut strut ends left a V-notch at every joint.

   *Fix:*
   * The strut nodes are inset by t/2. The inset comes out of the clear gap at
     the waist rather than the strut's lateral travel, so the re-entrant
     angles stay close to the original.
   * Every node gets a round boss, so the joints are filleted rather than
     notched.
   * The bands are clipped to the collar outline less 0.2 mm.
8. **The flange screw holes were half covered by the MCP block.** The Ø3 holes
   at ±7 mm sat under a block reaching ±7.7 mm, so screws couldn't pass.
   *Fix:* the flange is now 26 mm wide with holes at ±10 mm, which leaves
   clearance for M3 heads.
9. **The fingertip fillet always failed** (`BRep_API: command not done`), so
   the tip was flat.
   *Fix:* the tip is filleted on the plain loft before any cuts (r = 4 mm).
10. **The fingertip tendon channel ran past its anchor.** It went to 1 mm short
    of the tip, past the anchor hole. The anchor hole only lined up because it
    shared the old fixed −3 mm offset.
    *Fix:* the channel now ends at the anchor hole, which sits on the DIP
    tendon line.
11. **Dead code removed.** `socket_cut` and `add_hardstop_nub` were never
    called, and the latter was also on the wrong side. The `fillet` argument
    of `tapered_box` was never used.

### Changes made to support the fixes

* **The modules have a 0.8 mm full-section collar between each tab and the
  lattice.** The lattice is sized to the joint block, not to the tab. The tab
  is now smaller, because the socket has walls, so the lattice needs a
  full-size face to attach to. The collar also gives the module a positive
  axial seat against the phalanx end face.
* **Each phalanx is 0.8 mm shorter at every end that faces a joint.** This
  takes up the collars. Phalanx 1 goes from 32.86 to 31.26 mm, Phalanx 2 from
  17.76 to 16.16 mm and Phalanx 3 from 15.98 to 15.18 mm. Overall finger
  length (95.70 mm from flange face to tip) and lattice lengths are the same
  as before.
* **The DIP has its own `pulley_r` of 3.0 mm.** It was `None`, with the
  original script hard-coding −3.0 mm at the call site.

## Not checked

* No stiffness or FEA has been run on any variant. The angles and volumes in
  `variants_summary.csv` are geometry only.
* The hard stops still aren't sized to a flexion angle. Their side and
  attachment are fixed, but the 90° / 100° / 80° limits in the comments have
  not been checked against the assembly. Check them in CAD before printing.
* Printability of the thinnest struts (0.405 mm at the DIP palmar side of
  `T090`) depends on your nozzle and TPU grade.
