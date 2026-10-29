# Where to anchor the flexor tendon on each phalanx

Script: [`scripts/tendon_pivot_optimizer.py`](../scripts/tendon_pivot_optimizer.py).
Results: [`results/tendon_pivot/`](../results/tendon_pivot/). Tests:
[`tests/test_tendon_pivot.py`](../tests/test_tendon_pivot.py).

**Every dimension in this analysis is a placeholder** carried over from an earlier
stand-alone script. The numbers below show how the method behaves. They are not
anchor positions to print.

## Why the earlier optimiser gave no usable answer

The earlier script maximised `T = x F sin(x θ / (L + x))` over the anchor distance `x`
at each joint. All three strategies (average, worst case, critical angle) returned
`x = Lp`, the upper bound, at every joint. The pose-sweep CSV came out identical for
all three. Four separate faults caused this:

| # | Fault | Effect |
|---|---|---|
| 1 | Torque was maximised with nothing it had to be traded against. | A longer lever always gives more torque, so the optimum sat at the upper bound by construction. The script's own `monotonic_in_x_expected = True` flag was saying this. |
| 2 | The sine used the wrong angle of the guide–pivot–anchor triangle. | The moment arm is `x·sin(anchor angle)` = `L·sin(guide angle)` = `L x sinθ / √(L² + x² + 2Lx cosθ)`. The old formula is `x·sin(guide angle)`, which mixes the two. It fails the virtual-work check `r = −dℓ/dθ`. At the MCP with x = 45 mm and θ = 46° it gives 15.1 mm where the geometry gives 20.0 mm, about 24 % low. |
| 3 | "Worst case" took the minimum *raw torque* over the angle range. | Torque rises with angle, so the minimum is always the torque at `theta_min`, and the answer was simply whatever `theta_min` had been typed in. The worst case that matters is the smallest **margin**: available torque divided by required torque. |
| 4 | Each joint was optimised on its own. | One tendon flexes all three joints. They share one tension, and their excursions add up against one actuator stroke. |

## What a well-posed optimum is

By virtual work, the moment arm is the tendon excursion per radian. Each extra
millimetre of lever spends actuator stroke, so the optimum is a trade between torque
and stroke. The script states it in two ways:

* **min_stroke**: at each joint, the anchor that uses the least excursion while still
  holding the required torque × `SAFETY_FACTOR` at every pose in the grasp window.
* **max_margin**: the three anchors that maximise the smallest margin across the
  joints, with the summed excursion within the stroke. This is coupled across the
  joints and is solved by exhaustive search over the grid.

Required torque = TPU stiffness × angle (A3 CalculiX figure, provisional modulus)
+ the torque a fingertip force, normal to the distal phalanx, applies to that joint
through the chain. Tension and stroke come from the MG995 servo: `F = derate·τ/R` and
`s = R·π`. Their product is fixed, so the horn radius `R` is part of the design too.

## What the placeholder numbers say

**Collinear tendon (the old script's geometry), 5 N at the fingertip**
(`collinear_5N/`). No anchor position at any joint reaches a safety factor of 1.5. The
max-margin design (MCP 25.1, PIP 11.3, DIP 4.6 mm) uses the whole 31.4 mm stroke and
still only reaches a margin of 0.40. The binding pose is always the start of the
contact window (11.5°). A tendon that passes through the pivot has almost no moment
arm when the finger is nearly straight, and choosing a different `x` cannot fix that.

**4 mm palmar offset at every guide and anchor, 3 N** (`palmar4mm_3N/`). PIP and DIP
meet the safety factor with almost any anchor, because the offset provides the lever.
The MCP is the bottleneck. The max-margin design puts the MCP anchor at 22.6 mm and
reaches a margin of 1.35 within the stroke. The horn sweep shows that a smaller horn
(more tension, less stroke) helps once there is an offset.

So the real design variables are the **palmar offset of the tendon routing** and the
**horn radius**, more than the anchor distance. The MCP sets the limit.

## Limits

* The geometry is planar. The tendon runs straight from guide to anchor, with no
  wrapping, friction, stretch or bowstringing check.
* The grasp path is proportional flexion across a placeholder contact window.
* A margin ≥ 1 means the tendon *can* hold the load at that pose. It does not mean
  the underactuated finger will *reach* that pose. The unloaded closing-tension plot
  shows the order in which the joints close. With the A3 stiffness, all of them need
  less than about 1 N to flex, so the TPU spring barely affects strength. It does
  affect the closing sequence.

## Run it

```bash
python scripts/tendon_pivot_optimizer.py --palmar-offset-mm 4 --fingertip-force-n 3 --horn-radius-mm 10 --out results/tendon_pivot/my_run
```

To use real values, replace `JOINTS`, the servo block, `FINGERTIP_FORCE_N` and the
contact windows with measured CAD values.
