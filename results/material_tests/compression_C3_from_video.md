# Test C, cylinder C3: values read from the videos (2026-11-21)

Lever rig: the scale reads 1/30 of the force on the cylinder (force = scale × 30). The
compression was called out aloud in mm; the calls were taken from the audio with
speech-to-text (Whisper small) and the scale was read from the video frames at the moment
of each call. Cylinder Ø9.6 mm, height 9.6 mm (measured), plates not counted (0 mm).

## Video 22:24 (run 1 in the workbook): loaded fast, not in held steps

| Call (mm) | Time (s) | Scale (g) | Force on cylinder (N) | Note |
|---|---|---|---|---|
| 0.2 | 8.6 | 124.0 | 36.5 | scale rising fast (54–176 g within 2 s) |
| 0.3 | 12.0 | 278.8 | 82.1 | |
| 0.5 | 15.0 | 418.6 | 123.2 | rising fast (366–521 g) |
| 0.8 | 17.6 | 527.6 | 155.3 | |
| 0.9 | 21.0 | 762.1 | 224.3 | |
| 1.0 | 23.0 | 805.3 | 237.0 | rising fast |
| 1.1 | 24.1 | 960.3 | 282.6 | rising fast |
| 1.2–1.5 | 24.6–27.0 | 1051.8, 1045.1, 1147.7, 1213.1 | | called within 3 s; beyond 10 %, not used |

E (neo-Hookean, rows from 2 % to 10 %): **28.6 MPa** (rows 24, 35, 31, 24, 30 MPa).

## Video 22:43 (run 2 in the workbook): slow

| Call (mm) | Time (s) | Scale (g) | Force on cylinder (N) |
|---|---|---|---|
| 0.1 | 7.0 | 282.3 | 83.1 |
| 0.2 | 16.3 | 539.2 | 158.7 |
| 0.3 | 22.2 | 656.5 | 193.2 |
| 0.4 | 31.0 | 782.7 | 230.3 |
| 0.5 | 34.6 | 835.1 (815 g 1 s later) | 245.8 |

Calls 0.6–0.9 mm (55.9–75.2 s) are left out: at about 52 s the scale fell from 1,339 to
912 g and then jumped between 1,297 and 331 g while the calls went on rising. Something
moved, and the force cannot fall while the compression grows.

E from this run: 80.2 MPa, falling from 103 to 62 MPa with strain, because the start is
offset: 83 N already at the first 0.1 mm call, about ten times run 1's stiffness at the
start. The length reading was probably zeroed after loading had begun. Its incremental
slope from 0.2 to 0.5 mm (~38 MPa) is close to run 1's (~31 MPa).

## Video 18:56: not used (no length call-outs, only conversation)

## Verdict

C3 compression E ≈ **28.6 MPa, provisional** (one fast run). For a firm number, repeat
with held 0.2 mm steps (30 s each), the length gauge zeroed with the press just touching
(scale ≈ 0), and the ×30 lever factor checked once with a known weight in place of the
cylinder.
