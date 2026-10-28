# Firmware

Arduino sketches for the Barnes hand bench hardware. These are standalone
sketches, not part of the `barnes_ui` Python package: nothing in the
application imports or drives them. They exist so the bench setup used
alongside the software is recorded in the same repository.

Arduino's IDE requires a sketch to sit in a folder of the same name, so each
sketch gets its own directory.

## `servo_hold_45/`

Holds five hobby servos (MG995-class) at 45 degrees on an Arduino Uno, pins
3, 5, 6, 9 and 10 — the static pose used when setting finger servo angles
before a measurement.

The sketch is written around the power problem rather than the angle. Five
MG995s commanded to a new angle at the same moment draw a stall-order inrush
that collapses most bench supplies, which browns out the board and leaves the
servos buzzing at an angle nobody asked for. So:

- servos are attached and moved **one at a time**, never together;
- each one ramps a degree at a time (`STEP_MS` = 20 ms per degree) instead of
  being commanded straight to the target;
- only one servo is ever in motion — the other four are already holding.

Pulse limits are set to 600–2400 us for 0–180 deg. A servo that does not
reach 45 deg, or that hits an end stop, usually wants those limits adjusted to
its own datasheet rather than the angle changed.

### Wiring and power

- All servo **red** leads to an external 5–6 V supply (+), sized for the stall
  current of at least one servo plus the holding current of the rest.
- All servo **brown** leads to that supply's (−) **and** to Arduino GND; the
  grounds must be common or the pulse has no reference.
- Signal (orange/yellow) leads to pins 3, 5, 6, 9, 10.
- Keep the Arduino powered from USB, so a sag on the servo rail cannot reset
  the board mid-ramp.

### Changing the angle

`TARGET` is the held angle. `ATTACH_REST` (90) is where a servo lands when it
is first attached with no prior write — the library emits its default pulse —
and it is the assumed starting point of the ramp, so change it only if the
servo visibly settles somewhere else on attach.
