# Tendon routing: Type A (pinned) and Type B (TPU joint)

Scripts: [`scripts/type_a_geometry.py`](../scripts/type_a_geometry.py) (measures the
CAD) and [`scripts/tendon_routing_analysis.py`](../scripts/tendon_routing_analysis.py)
(the analysis). Results: [`results/tendon_routing/`](../results/tendon_routing/).
Tests: [`tests/test_tendon_routing.py`](../tests/test_tendon_routing.py). Method
background: [10-tendon-pivot-analysis.md](10-tendon-pivot-analysis.md).

**What is measured, and what is a placeholder.** All Type A geometry comes from the
hand assembly, `reference_parts/type_a_hand_assembly.step`. That covers pivots, link
lengths, hole positions, section depths and flexion stops. Three things are
placeholders:

* the load case: 5 N at the fingertip, grasp from 10° to 70 % of each joint's range;
* the actuator: MG995 at half stall on a 10 mm horn, giving 47 N and 31.4 mm;
* the TPU modulus: 12 MPa.

Forces scale with the actuator. Type B buckling limits also scale with the modulus.

## Summary

| | Type A, flush guides | Type A, guides standing proud | Type B, as built |
|---|---|---|---|
| Fingertip force the finger can hold (worst joint) | **3.0–3.4 N** | **4.3–6.2 N** | **0.02–3.3 N**, limited by flexure buckling |
| What limits it | servo stroke (all 31 mm used) | servo stroke | TPU leaves buckling under tendon tension |
| What sets it | how far below the centreline the tendon runs | same | the tendon offset `d`, capped by the section |
| Where along the phalanx the guide sits | changes force by ≤ 20 % | same | no choice: the joint rotates where the flexure bends |

**The main result.** In Type A, *where* along the phalanx the guide sits hardly
matters. *How far below the joint axis* the tendon runs decides almost everything.
In Type B, the tendon must squeeze the joint to bend it. Every Type B variant
buckles at a small fraction of the tension the servo can apply.

## Type A: what was measured

From the assembly, per finger:

| | Index | Middle | Ring | Little |
|---|---|---|---|---|
| MCP | ball, R 5.44 | ball, R 5.26 | ball, R 5.26 | ball, R 4.50 |
| PP / MP / DP length (pivot to pivot, DP to tip) | 41.88 / 26.54 / 16.95 | 46.52 / 31.19 / 18.34 | 43.49 / 29.51 / 18.61 | 33.95 / 21.15 / 16.12 |
| PIP flexion stop, from straight | 110° | 111° | 117° | 124° |
| **DIP flexion stop, from straight** | **40°** | **50°** | **51°** | **50°** |
| Holes MC / PP / MP / DP | 10 / 4 / 3 / 2 | 9 / 5 / 3 / 2 | 9 / 4 / 3 / 2 | 7 / 3 / 2 / 2 |

The index PIP pin lies at 41.875 mm from the MCP centre. That matches the
independent measurement of the same finger on branch `claude/sweet-curie-3r59na`.

**The DIP only flexes to 40–51°.** A human DIP reaches about 80–90°. An exact solid
intersection of the index DP rotated against the MP (OpenCASCADE `BRepAlgoAPI_Common`)
finds no overlap from straight to 6° past the DP's rest pose, then 1.9 mm³ at 8° and
16 mm³ at 40°. The stop is real, in the CAD. If it is not intended, it is the first
thing to change. The MCP is a ball with no stop, so 90° is assumed there.

**The phalanges are thin bars that sit dorsal of the pin line.** At mid-length, the
palmar surface is only 0.5–4.5 mm below the line through the pivots. A guide that is
flush with the palmar face therefore sits close to the joint axis, and the lever is
small.

## Type A: the full-length sweep

For each joint, the sweep covers:

* the guide on the proximal link, over the whole link, from the joint head
  (cam or ball radius + 2.4 mm) to the next joint's head;
* the guide on the distal link, over the same span;
* the palmar offset `h` of the tendon below the line through the pivots.

That is 28 × 28 × 25 combinations per joint. Each one is scored on the fingertip
force it can hold at its worst grasp pose and on tendon excursion. Two rules are
enforced:

* the tendon must flex the joint at every angle, so its lever stays positive;
* the two guides must stay at least 3.5 mm apart.

A coupled search then picks one design per joint so the three excursions fit the
stroke.

**Flush guides** (`type_a_flush/`). The guide stays inside the palmar surface:

| Finger | MCP: a / x / h (mm) | PIP: a / x / h | DIP: a / x / h | Fingertip force |
|---|---|---|---|---|
| Index | 19.8 / 11.8 / 4.8 | 10.5 / 7.6 / 2.4 | 8.3 / 7.7 / 0.6 | 3.4 N |
| Middle | 17.2 / 38.9 / 3.9 | 7.6 / 7.6 / 2.5 | 7.4 / 7.4 / 0.6 | 3.0 N |
| Ring | 7.7 / 8.7 / 5.5 | 35.8 / 7.6 / 2.2 | 21.9 / 11.2 / 0.0 | 3.2 N |
| Little | 32.6 / 23.5 / 2.2 | 10.5 / 8.3 / 1.7 | 7.6 / 7.7 / 0.4 | 3.2 N |

**Guides standing proud of the palmar face** (`type_a_standoff/`, `h` up to 12 mm).
This is how the prototype's screws can be used:

| Finger | MCP h | PIP h | DIP h | Fingertip force |
|---|---|---|---|---|
| Index | 8.0 mm | 4.0 mm | 1.5 mm | 5.2 N |
| Middle | 8.0 | 3.5 | 1.0 | 4.3 N |
| Ring | 7.5 | 4.0 | 1.0 | 4.5 N |
| Little | 8.0 | 4.0 | 1.5 | 6.1 N |

`a` is the guide on the proximal link, measured back from the joint; `x` is the guide
on the distal link, measured from the joint; `h` is the offset below the line through
the pivots.

**The best distance from the centreline** is therefore about **7.5–8 mm at the MCP,
3.5–4 mm at the PIP and 1–1.5 mm at the DIP**. The values fall from MCP to DIP
because each joint carries a smaller share of the fingertip moment. They are not
larger still because tendon excursion grows with `h`, and all three joints share one
stroke. With a different servo or horn, rerun the script; the split will move.

Measured from the palmar face, those offsets mean the MCP guide stands about 3–5 mm
proud and the PIP guide about 1–2 mm proud.

**How much each variable matters.** Range of fingertip force across each sweep, with
the other variables held at the optimum (`sweeps.csv`):

* offset `h`: from about 0.6 N to 7 N or more at every joint;
* guide station along the proximal link: 2–20 %;
* guide station along the distal link: 2–20 %.

Guides further from the joint add a little torque at large angles (the tendon
bowstrings) and cost a little more excursion. Guides close to the joint act like a
pulley of radius `h`.

**Using the holes you already drilled** (`existing_holes_best.csv`). The same coupled
search, restricted to the drilled holes, gives 2.0–3.0 N flush and 3.6–5.2 N standing
proud. That is 75–90 % of the continuous optimum. For the index finger, standing
proud:

| Joint | Proximal hole (mm from the pivot) | Distal hole (mm from the pivot) | Offset h |
|---|---|---|---|
| MCP | MC hole at 10.35 | PP hole at 15.25 | 6.5 mm |
| PIP | PP hole at 8.81 | MP hole at 13.31 | 3.0 mm |
| DIP | MP hole at 13.22 | DP hole at 12.03 | 0.5 mm |

Every hole sits on the centreline. What a screw changes is `h`, so the screw length
(how far it stands out below the bar) is the adjustment that matters.

## Type B: a different analysis, because there is no pivot to place

Variants are from branch `claude/keen-keller-s1cv0n`: B1, B3, B5, B6 and the lattice,
55 in all. Their tables are copied to `type_b_inputs/`.

**Where the joint rotates.** B3, B6, the full-length B1 notch and the lattice bend
along their length. Their centre of rotation starts at mid flex zone and moves as
the joint closes. By 105° it has moved 1–1.3 mm along the axis and 1.9–2.6 mm towards
the palm (`type_b.png`, top left). B5 (crossed strips) and the 50 % B1 notch hold the
centre near mid flex zone by construction. Both of those figures ignore the drift
caused by compression, which is the larger effect below.

**The tendon's lever.** The tendon crosses the flex zone in open air at offset `d`
from the flexure's neutral axis. Its lever comes from virtual work on the bent shape:
it starts at `d` and stays within 0.5 mm of it for a bending joint. At the as-built
offsets (MCP / PIP / DIP = 3.06 / 1.93 / 1.06 mm), the MCP needs **24–26 N of tendon
per newton at the fingertip**.

**Compression is the problem.** The tendon's tension squeezes every joint between the
anchor and the servo. In Type A the pin takes that load. In Type B the TPU must. At
E = 12 MPa, fixed-fixed Euler buckling of the leaves gives:

| Variant (best of family) | Buckles at | Fingertip force at buckling | Servo-limited fingertip force |
|---|---|---|---|
| B1_t200_notch050 | 78 N (DIP) | 3.3 N | 1.9 N |
| B3_t200_w30 | 19 N | 0.74 N | 1.8 N |
| B5_t200_a45 | 15 N | 0.62 N | 1.9 N |
| B6_n4_t200 | 13 N | 0.50 N | 1.8 N |
| thinnest variants | 1–2 N | 0.02–0.03 N | 1.8–1.9 N |

At full servo tension, the axial strain in the weakest joint would be 40–165 %. A
Type B joint loaded this way collapses before it bends.

**The best tendon offset for Type B** is as large as the section allows: tension
falls as `1/d` (`type_b.png`, bottom left). Moving the tendon channel to the deepest
offset the section permits (MCP 4.7, PIP 3.7, DIP 2.7 mm) cuts the MCP tension from
about 27 to 17 N per newton at the fingertip, and lifts the servo limit to about
2.7 N. It does not remove the buckling limit.

Type B needs something that carries the compression. Options:
* a rolling-contact surface (the B4 idea);
* a contact pad across the joint;
* a compression strut on the neutral axis.

The leaves would then be left to supply only the return spring. The B1 50 % notch
does best here simply because its throat is short.

## Limits

* Planar statics, one tendon, straight runs between guides. No friction at guides,
  no tendon stretch, no wrapping on the joint heads.
* For Type A the stop angles are CAD intersections. Points are sampled to 0.5°, and
  the index DIP was confirmed with an exact solid boolean.
* For Type B, the buckling loads are Euler fixed-fixed with the thinnest section. The
  lattice was not estimated. Eccentric tendon loading would lower the true buckling
  load further. Both the buckling loads and the axial strains are linear in the
  uncalibrated modulus.
* Fingertip forces are for the placeholder actuator. Fingertip force × excursion is
  roughly fixed by the servo's work, so a different horn trades one against the other.

## Rerun

```bash
python scripts/type_a_geometry.py
```

The full geometry run takes about 40 minutes, almost all of it the flexion-stop
search. To refresh only the section depths, which takes about a minute:

```bash
python scripts/type_a_geometry.py --envelopes-only
```

Then run the analysis, which takes about a minute:

```bash
python scripts/tendon_routing_analysis.py
```
