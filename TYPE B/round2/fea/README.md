# Round-2 tendon-load FEA

Does each shortlisted Type B joint carry the tendon's compression? One JSON per
joint and pose in `results/`, written by [`../fea_round2.py`](../fea_round2.py) and run by
[`../run_round2_campaign.py`](../run_round2_campaign.py). The method is in the
docstring of `fea_round2.py`; the discussion is in section 5 of
[`docs/report/BARNES_print_decision_report.pdf`](../../../docs/report/BARNES_print_decision_report.pdf).

Capacity is the tendon tension at which the joint, held at the pose, first buckles,
collapses or reaches 20 % peak strain. E = 12 MPa; every capacity scales with E.

| Joint | 0° (N) | 60° (N) | Hand estimate (N) | Limited by (0°) |
|---|---|---|---|---|
| B1_t200_notch050 | 24.9 | 0: 68 % strain from the bend alone | 133 | 20 % strain |
| B3_t200_w30 | 10.0 (10.1 at 30°) | 8.6 | 33.2 | sideways buckling |
| B5_t200_a45, deep tendon | **30.2** | **10.3** | 34.1 | 20 % strain |
| B5_t150_a45 (as built and deep) | 16.8 | 6.4 | – | buckling (limit point) |
| B9_n150 | 12.7 | 0: 37 % strain from the bend alone | 14.0 | 20 % strain |
| B4_t100_a60, deep tendon | ≥ 11.1 (12 % strain) | not resolved | 19.0 | contact diverged (guided) |
| B8_y00_r150 | ≥ 5.8 (16 % strain) | not resolved | 28.1 | contact diverged (guided) |
| B8_y20_r125 | ≥ 4.9 (6 % strain) | not resolved | 23.4 | contact diverged (guided) |

Bearing joints (B4, B8) are run *guided*: driven along the tendon line under
displacement control. Under a free load their thin return leaves buckle sideways at
about 0.3 N and the joint snaps across its 0.3 mm gap before the bearing seats, which
CalculiX could not follow. "≥" marks a lower bound: the contact solution stopped
before the bearing reached any limit.

Deep copies whose flexure is unchanged share the as-built run (only the tendon's
lever differs, which the report applies). At 0° the deep and as-built decks are
identical.

    python run_round2_campaign.py          # every job not yet in results/
    python fea_round2.py B5_t200_a45 --offset deep --angle 60
