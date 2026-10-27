"""Whole-hand kinematics and reduced-order joint coupling.

Phase 5. This package is where the application becomes visually convincing, which is
exactly why the separation between its two modes is enforced in the type system rather
than in a label someone can forget to render.

**Mode 1, kinematic preview.** Rigid links rotating about confirmed axes. It answers
"does it reach" and "does it collide". It knows nothing about force, and
:class:`~barnes_ui.core.kinematics.modes.KinematicPose` has nowhere to put a torque.

**Mode 2, reduced-order dynamics.** The same motion, with a restoring torque supplied
by a spring fitted to an FEA torque-angle curve. Every result carries the caveats that
come with condensing a deformable body into a scalar spring, and refuses to
extrapolate past the angles the FEA actually covered.

An animation is not a simulation. A smooth animation of a hand closing, with a torque
plotted beside it, is the single most persuasive and least verified thing this
application can produce.
"""

from __future__ import annotations

__all__: list[str] = []
