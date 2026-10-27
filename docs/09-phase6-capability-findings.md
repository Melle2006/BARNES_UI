# Phase 6 — what the solver can and cannot do here

Phase 6 is the investigative phase, with a permitted negative outcome. "We tried
self-contact, here is the evidence, it does not meet the criterion" is a successful
result. This document records what was tried, what the answer was, and — in two cases
— what the answer looked like before the benchmark was posed correctly.

Everything here is a statement about **CalculiX 2.23, the official Windows build,
running on one machine, on these benchmark geometries**. That is the only form in
which the question has a useful answer. The machine-readable version lives in
`results/phase6/capabilities.json`, is written by `scripts/phase6_benchmarks.py`, and
is what the application reads before offering a feature.

---

## The gate

`core/fea/capabilities.py` holds a registry with four statuses:

| Status | Meaning |
|---|---|
| `NOT_TESTED` | No benchmark has been run here. **The feature is disabled.** |
| `PASSED` | A benchmark with an answer known in advance was reproduced within tolerance. |
| `FAILED` | It was run and was not reproduced. Phase 6 permits this. |
| `NOT_AVAILABLE` | The solver does not have the feature. No benchmark can change it. |

A fresh checkout starts with everything `NOT_TESTED`, so everything is off. That
asymmetry is the point: a capability is enabled by evidence, not by the absence of
evidence against it.

`CapabilityRegistry.require()` raises with the recorded evidence rather than a bare
"unsupported", because the reader's next question is always "says who".

---

## Results

| Capability | Verdict | Measured |
|---|---|---|
| Gravity (body load) | **PASSED** | Cantilever self-weight tip deflection −1.21 % against the closed form |
| Tendon load (point force) | **PASSED** | 2 N resultant over a 119-node patch; root reaction 2 N, 0.000 % |
| Frictionless contact | **PASSED** | 100 N through a stacked-block interface, 0.000 %; 0.0041 mm penetration on a 4 mm element |
| Contact with friction | **PASSED** | μ = 0.3, tangential reaction exact, 0.0068 mm of in-plane motion |
| Mechanical stops | **PASSED** | Tip deflection 0.5017 mm against a 0.5 mm gap, +0.3 % |
| Self-contact | **PASSED** | Closest approach +0.067 mm — positive, so no overlap. Mesh-independent across a 2.7× refinement; the same model without contact overlaps by 8.02 mm |
| Viscoelasticity | **NOT AVAILABLE** | No such material model in CalculiX. Settled in Phase 3 against the manual |

### Gravity

A 60 × 8 × 4 mm cantilever at 1.2 g/cm³ under standard gravity, against

    δ = q L⁴ / (8 E I) + q L² / (2 G A_s),   A_s = (5/6) A

Tip deflection 0.0141902 mm against 0.0143642 mm. The 1.2 % the model is stiff is the
same physics as the Phase 3 cantilever: a fully clamped end face restrains the Poisson
contraction beam theory allows freely.

Worth the few seconds it takes because it exercises three things at once — the
`*DENSITY` path, the `*DLOAD, GRAV` path, and the tonne-per-cubic-millimetre unit
system. A density entered in g/cm³ would overstate every force by a factor of 10⁹ and
the run would converge perfectly.

### Tendon load

`*CLOAD` on a node set applies the stated force to **every node in it**. A 2 N tendon
on a 119-node patch becomes 238 N, and the deformed shape still looks like a tendon
pulling. `PointLoad(total=True)` divides the resultant; this benchmark is what proves
it divides it correctly, by global equilibrium at the root.

### Contact, and the finding that contradicted the code's own comment

The conventional view — and what `core/fea/contact.py` said when it was written — is
that node-to-surface is the robust formulation and surface-to-surface the fragile one.
Measured here, it is the other way round:

| Configuration | Two blocks, 100 N | With friction | Hairpin |
|---|---|---|---|
| node-to-surface, K = 10E/h | did not converge | did not converge | did not converge |
| node-to-surface, K = E/h | did not converge | did not converge | did not converge |
| surface-to-surface, K = 10E/h | **14 increments** | **14 increments** | **24 increments** |

Node-to-surface failed by chatter rather than divergence: individual increments
reported "convergence" while the increment size was cut again and again until it fell
below the minimum. The benchmark script now tries configurations in order and records
which one worked, so the evidence names the setting instead of the setting quietly
becoming an assumption.

`ContactFormulation.SURFACE_TO_SURFACE` requires **both** surfaces to be element-face
based; only node-to-surface accepts a bare node set as the slave. `ContactPair` now
refuses the invalid combination rather than letting CalculiX reject the deck.

### Friction

The same stack with μ = 0.3 and a tangential load at a third of the Coulomb limit.
Nothing restrains the upper block in plane except friction, so **convergence is itself
part of the result**: a formulation that failed to engage would let the block slide
off and the solve would diverge. Peak in-plane displacement 0.0068 mm, against a 4 mm
element.

### Mechanical stops

A cantilever loaded to three times the force that just closes a 0.5 mm gap onto a
fixed shelf. Once it is on the stop, its tip deflection is the gap — no FEA needed for
the expected answer. A stop that was not engaging would give 1.5 mm. Measured
0.5017 mm, +0.3 %.

---

## Self-contact: four set-ups, three of them wrong

The entry that took longest and taught most. Every failure looked like a solver
limitation and none of them was one. See risk R13.

**Attempt 1 — every surface as both slave and master.** The textbook self-contact
recipe. Here it meant every node began in contact with the face it belongs to. It
diverged in the first increment. Naming the two walls that can actually meet is
cheaper and better posed, and the hairpin's geometry says exactly which they are.

**Attempt 2 — a prescribed displacement larger than the gap.** Contact cannot resist
a prescribed displacement: the node goes where it is told. One leg went straight
through the other. **The run converged**, raised no error, and reported a closest
approach of exactly minus the overshoot. The only visible symptom was 129 convergence
cutbacks. Recording "CalculiX self-contact does not work" at this point would have put
a false limitation into the documentation permanently.

**Attempt 3 — a closing force, which contact can balance** — and a measurement that
was still wrong. A 1.0 N force on a hairpin whose legs are worth about 0.21 N/mm
would close roughly 4.7 mm if nothing stopped it. It closed about 1.1 mm against a
1.0 mm gap, so contact plainly engaged — but the reported closest approach was
−0.108 mm, and the benchmark was recorded as FAILED on 12 % of an element of
apparent interpenetration.

**Attempt 4 — measuring a gap where a gap exists.** The separation was being taken as
the *lowest* point of the upper leg against the *highest* point of the lower one,
over the whole straight run. Both legs bend, so their extremes sit at different
stations, and the difference between two points that are not above one another is not
a gap anywhere. Binned along the deformed x axis and compared station by station, the
closest approach is **+0.067 mm — positive. The legs never overlapped.**

### How the measurement error was caught

Not by review. By the refinement diagnostic in
`scripts/selfcontact_refinement.py`, which was written to test a different
hypothesis entirely — that the overlap was an edge contact a finer mesh would
resolve. It made a prediction: if the overlap is discretisation, it falls with the
element size.

| element size | apparent penetration | as % of element |
|---|---|---|
| 1.20 mm | 0.1179 mm | 9.8 % |
| 0.90 mm | 0.1079 mm | 12.0 % |
| 0.60 mm | 0.1151 mm | 19.2 % |
| 0.45 mm | 0.1078 mm | 24.0 % |

Flat. Across a 2.7× refinement the number did not move, and it does not move with the
penalty stiffness either — which scales as 1/h, so a penalty-driven overlap would
have fallen with the mesh too. A quantity indifferent to both is not a property of
the solution. That is what pointed at the measurement.

The hypothesis the diagnostic was built to test turned out to be wrong, and it found
the real fault anyway, because it predicted something specific and the prediction
failed in a way that was itself informative.

### The control the benchmark should have had from the start

With the corrected measurement, the closest approach is +0.057 to +0.067 mm across
the same refinement sequence — mesh-independent and on the correct side of zero,
which is what a working contact looks like.

That still does not prove contact did anything, so the diagnostic now runs a
**control**: the identical model with the contact pair removed. The legs overlap by
**8.02 mm**. Against +0.06 mm with contact, there is no remaining doubt about what
stopped them.

A benchmark that only ever runs *with* the feature cannot distinguish "contact held
them apart" from "they were never going to touch". This one spent three set-ups
unable to make that distinction. `benchmark_self_contact(..., with_contact=False)`
exists so the next capability does not have to.

### Reproducing

```
python scripts/selfcontact_refinement.py --sizes 1.2 0.9 0.6 0.45 --control
```

## Viscoelasticity

Settled in Phase 3 criterion 8 against the manual, and recorded here for completeness:
CalculiX has no viscoelastic material model. There is no `*VISCOELASTIC` keyword — the
index runs `*VIEWFACTOR` straight to `*VISCO` — `*VISCO` is a step card for
viscoplastic analysis rather than a material, `*CREEP` is irreversible overstress creep
requiring `*ELASTIC`, and no `*HYPERELASTIC` model carries time or rate dependence. A
`umat` is the only route and is not documented as supported.

TPU genuinely creeps, relaxes and shows hysteresis. None of it is modelled, every
result carries `CAVEAT_NO_VISCOELASTICITY`, and no benchmark will change that status.

---

## What none of this says

Every benchmark here is between 1,700 and 8,000 second-order tetrahedra and finishes
in minutes. The A3 flexure is 33,000 elements and takes half an hour **without**
contact. Nothing has been attempted at that scale, so "contact works" means "contact
works on a stacked pair of blocks", and extrapolating it to a closing meander is
exactly the kind of inference this document exists to prevent.

## Reproducing this

```
python scripts/phase6_benchmarks.py
```

Each benchmark writes its verdict, its measured value, its convergence record and its
run archive path into `results/phase6/capabilities.json`. The archives hold the deck
exactly as submitted and the full solver log, so a reader who doubts a conclusion can
read the input rather than the code that generated it.
