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
tab and socket at every joint.

`verify_type_b.py` does a fuller geometric check of every variant and writes
the results to `verification_report.csv`. All variants pass all 35 checks:

```bash
python "TYPE B/verify_type_b.py"
```

It checks the following, on the assembled finger in its straight pose:

* **Tendon and sensor-lead routing.** A rod 0.1 mm under the channel diameter
  is run along the whole path, from the flange to the fingertip anchor,
  including the bends in the phalanges and the open-air run down the
  lattice's central corridor. It must not touch anything.
* **Fit.** Tab-to-socket radial clearance is 0.3 mm. Every socket wall is
  1.2 mm.
* **Material in the TPU tabs.** At least 0.8 mm around each channel, and at
  least 0.3 mm between each pin hole and the tendon channel or the side wall.
* **Holes.** The retention pins, flange screw holes, M3 head clearance on the
  flange, anchor-boss holes and fingertip tendon anchor hole are all clear.
* **Feature side.** Every nub and boss is on the palmar side.

It does not check how the lattice flexes, joint stiffness, or whether the hard
stops engage at the intended angles. Those need FEA or a test print.

## Folder layout

| Path | Contents |
|---|---|
| `build_finger_type_b.py` | The generator: every parameter, variant definition and check |
| `verify_type_b.py` / `verification_report.csv` | The geometric verification and its results |
| `previews/` | Rendered images of the assembled finger, the parts and the variant grid |
| `common_phalanges/` | `02_Phalanx1`, `04_Phalanx2` and `06_Phalanx3` as STEP and STL. The phalanges don't depend on the lattice, so the same files are used for every variant. |
| `B00_baseline/` | Your original lattice parameters with the errors corrected |
| `B_T###_X#/` | One folder per variant |

Every variant folder holds `01_MCP_module_with_flange`, `03_PIP_module` and
`05_DIP_module` as STEP and STL, plus `finger_assembly.step`. The assembly is
the whole finger, modules and phalanges, in position.
| `variants_summary.csv` | Cell count, strut thickness, re-entrant angle, cell height, tendon moment arm and module volume for each joint of each variant |

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

| Variant | Joint | Palmar: cells × strut (angle) | Dorsal: cells × strut (angle) | Module volume (mm³) |
|---|---|---|---|---|
| `B00_baseline` | MCP | 3 × 0.7 mm (54.2°) | 2 × 1.4 mm (23.5°) | 3054.4 |
| `B00_baseline` | PIP | 2 × 0.55 mm (45.2°) | 2 × 1.1 mm (22.8°) | 860.7 |
| `B00_baseline` | DIP | 3 × 0.45 mm (50.7°) | 2 × 0.9 mm (18.5°) | 539.8 |
| `B_T090_X2` | MCP | 2 × 0.63 mm (42.1°) | 1 × 1.26 mm (13.3°) | 3006.8 |
| `B_T090_X2` | PIP | 2 × 0.495 mm (46.2°) | 1 × 0.99 mm (12.9°) | 837.8 |
| `B_T090_X2` | DIP | 2 × 0.405 mm (38.3°) | 1 × 0.81 mm (10.5°) | 517.8 |
| `B_T090_X3` | MCP | 3 × 0.63 mm (55.2°) | 2 × 1.26 mm (26.5°) | 3039.7 |
| `B_T090_X3` | PIP | 3 × 0.495 mm (59.3°) | 2 × 0.99 mm (26.1°) | 857.6 |
| `B_T090_X3` | DIP | 3 × 0.405 mm (51.7°) | 2 × 0.81 mm (21.5°) | 529.2 |
| `B_T090_X4` | MCP | 4 × 0.63 mm (63.9°) | 3 × 1.26 mm (38.4°) | 3077.3 |
| `B_T090_X4` | PIP | 4 × 0.495 mm (67.7°) | 3 × 0.99 mm (38.4°) | 879.3 |
| `B_T090_X4` | DIP | 4 × 0.405 mm (61.2°) | 3 × 0.81 mm (32.3°) | 542.1 |
| `B_T100_X2` | MCP | 2 × 0.7 mm (41.1°) | 1 × 1.4 mm (11.6°) | 3023.1 |
| `B_T100_X2` | PIP | 2 × 0.55 mm (45.2°) | 1 × 1.1 mm (11.1°) | 853.9 |
| `B_T100_X2` | DIP | 2 × 0.45 mm (37.3°) | 1 × 0.9 mm (8.9°) | 528.5 |
| `B_T100_X3` | MCP | 3 × 0.7 mm (54.2°) | 2 × 1.4 mm (23.5°) | 3054.4 |
| `B_T100_X3` | PIP | 3 × 0.55 mm (58.4°) | 2 × 1.1 mm (22.8°) | 873.6 |
| `B_T100_X3` | DIP | 3 × 0.45 mm (50.7°) | 2 × 0.9 mm (18.5°) | 539.8 |
| `B_T100_X4` | MCP | 4 × 0.7 mm (63.1°) | 3 × 1.4 mm (34.6°) | 3090.0 |
| `B_T100_X4` | PIP | 4 × 0.55 mm (67.0°) | 3 × 1.1 mm (34.1°) | 894.9 |
| `B_T100_X4` | DIP | 4 × 0.45 mm (60.3°) | 3 × 0.9 mm (28.2°) | 552.5 |
| `B_T110_X2` | MCP | 2 × 0.77 mm (40.1°) | 1 × 1.54 mm (9.9°) | 3039.3 |
| `B_T110_X2` | PIP | 2 × 0.605 mm (44.2°) | 1 × 1.21 mm (9.2°) | 870.4 |
| `B_T110_X2` | DIP | 2 × 0.495 mm (36.2°) | 1 × 0.99 mm (7.4°) | 540.0 |
| `B_T110_X3` | MCP | 3 × 0.77 mm (53.2°) | 2 × 1.54 mm (20.3°) | 3068.7 |
| `B_T110_X3` | PIP | 3 × 0.605 mm (57.5°) | 2 × 1.21 mm (19.2°) | 889.4 |
| `B_T110_X3` | DIP | 3 × 0.495 mm (49.6°) | 2 × 0.99 mm (15.4°) | 551.0 |
| `B_T110_X4` | MCP | 4 × 0.77 mm (62.2°) | 3 × 1.54 mm (30.5°) | 3101.8 |
| `B_T110_X4` | PIP | 4 × 0.605 mm (66.2°) | 3 × 1.21 mm (29.4°) | 909.9 |
| `B_T110_X4` | DIP | 4 × 0.495 mm (59.3°) | 3 × 0.99 mm (23.8°) | 563.2 |
| `B_T120_X2` | MCP | 2 × 0.84 mm (39.0°) | 1 × 1.68 mm (8.2°) | 3059.7 |
| `B_T120_X2` | PIP | 2 × 0.66 mm (43.1°) | 1 × 1.32 mm (7.4°) | 879.5 |
| `B_T120_X2` | DIP | 2 × 0.54 mm (35.1°) | 1 × 1.08 mm (5.8°) | 552.3 |
| `B_T120_X3` | MCP | 3 × 0.84 mm (52.2°) | 2 × 1.68 mm (17.0°) | 3087.8 |
| `B_T120_X3` | PIP | 3 × 0.66 mm (56.5°) | 2 × 1.32 mm (15.5°) | 897.2 |
| `B_T120_X3` | DIP | 3 × 0.54 mm (48.4°) | 2 × 1.08 mm (12.2°) | 562.8 |
| `B_T120_X4` | MCP | 4 × 0.84 mm (61.3°) | 3 × 1.68 mm (26.0°) | 3119.1 |
| `B_T120_X4` | PIP | 4 × 0.66 mm (65.4°) | 3 × 1.32 mm (24.2°) | 915.8 |
| `B_T120_X4` | DIP | 4 × 0.54 mm (58.2°) | 3 × 1.08 mm (19.2°) | 574.2 |

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
   tab, giving **effective moment arms of 3.06 / 1.93 / 1.06 mm (MCP / PIP / DIP)
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
   *Fix:* the flange is now 28 mm wide with holes at ±11 mm. An M3 head
   (Ø5.5) then clears the block, which the verification confirms. A first
   attempt at ±10 mm still clipped the block by 0.45 mm.
9. **The fingertip fillet always failed** (`BRep_API: command not done`), so
   the tip was flat.
   *Fix:* the tip is filleted on the plain loft before any cuts (r = 4 mm).
10. **The fingertip tendon channel ran past its anchor.** It went to 1 mm short
    of the tip, past the anchor hole. The anchor hole only lined up because it
    shared the old fixed −3 mm offset.
    *Fix:* the channel now ends at the anchor hole, which sits on the DIP
    tendon line.
11. **The proximal sockets thinned with the taper.** A phalanx is thinnest at
    the floor of its proximal socket, so a socket sized to its end face left a
    0.92 mm wall at the proximal end of Phalanx 2.
    *Fix:* each proximal socket is sized to the phalanx section at the socket
    floor, and so is the distal tab of the joint module that fits it. Every
    wall now measures 1.2 mm.
12. **Dead code removed.** `socket_cut` and `add_hardstop_nub` were never
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
