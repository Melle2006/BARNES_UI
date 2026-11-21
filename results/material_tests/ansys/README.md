# TPU test data for ANSYS

Made by `scripts/export_ansys_csv.py` from `../tension_tests_AB.xlsx` and
`../compression_test_C.xlsx`. All values are **engineering strain (mm/mm)** and
**engineering stress (MPa)**, as ANSYS expects for hyperelastic test data. Compression is
negative.

| File | What | Use it for |
|---|---|---|
| `uniaxial_tension_edge.csv` | E1-1 + E2-1 (strips printed on edge) | **the main material data**: joint leaves and strips are printed this way |
| `uniaxial_edge_tension_plus_compression.csv` | the edge tension and C1 compression in one table | a hyperelastic fit that covers both tension and compression |
| `uniaxial_tension_flat.csv` | F1-1 + F2-1 (dog-bones printed flat) | comparison, or parts printed flat |
| `uniaxial_compression.csv` | C1 | compression only |
| `raw/<specimen>.csv` | every reading as measured, one file per specimen | checking; not cleaned |
| `apdl/*.txt` | the same four tables, no header, space separated | Mechanical APDL curve fitting |
| `summary.csv` | E per specimen and group, neo-Hookean μ and D1 | quick values |

"Fit-ready" tables (the four top-level files): (0, 0) kept once; readings with stress but
no measurable strain dropped (the gap was read to 0.1 mm = 0.5 % strain, so the first one or
two steps of F1-1 and E1-1 read zero; left in, they look like infinite stiffness and spoil the
fit); sorted by strain; readings at the same strain averaged. C2 is left out (its start is
offset, see `../compression_C1_C2_from_video.md`).

## ANSYS Workbench (Engineering Data)

1. Engineering Data → your TPU material → Toolbox → **Hyperelastic Experimental Data →
   Uniaxial Test Data**, drag it onto the material.
2. Open the CSV in Excel, select the two columns **without the header row**, copy, and paste
   into the Uniaxial Test Data table (Strain, Stress). Set the table's units to mm mm⁻¹ and
   MPa if they are not already.
3. Add a hyperelastic model (Toolbox → Hyperelastic): **Neo-Hookean** is enough for these
   strains (up to ~18 %); Mooney-Rivlin 2-parameter or Yeoh 2nd order if you want a closer
   fit. Right-click it → **Solve Curve Fit**, check the plot against the points, then
   **Copy Calculated Values to Property**.
4. Or skip the fit and type the neo-Hookean values from `summary.csv` directly:
   μ = 6.99 MPa, D1 = 0.00573 MPa⁻¹ (ν = 0.49) or 0 (incompressible).

## Mechanical APDL

```
TB,HYPER,1,,,NEO
TBFT,EADD,1,UNIA,uniaxial_tension_edge.txt
TBFT,SOLVE,1,HYPER,NEO,1
TBFT,FADD,1,HYPER,NEO
```

## Caveats

* One copy of each tension specimen and one usable compression run: treat these as
  provisional until the other copies are tested.
* The conditioning mass in the workbook reads 0.045–0.06 kg rather than the ~1–2 kg asked
  for; if that is what was hung, the specimens were not conditioned, and the first-stretch
  (Mullins) stiffening is in the data.
* Compression (C1, 28.6 MPa) reads about 35 % stiffer than tension (21.0 MPa). Some of that
  is normal for a short cylinder; the run was also loaded fast. A neo-Hookean fit to the
  combined table will sit between the two.
