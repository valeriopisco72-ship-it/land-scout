# land-scout

**Land screening for renewable energy siting — Italian cadastral, regulatory and grid data.**

Given an area and a technology (utility-scale PV, agrivoltaics, BESS), land-scout scores
individual cadastral parcels, aggregates them into contiguous blocks large enough to be
worth a developer's attention, and reports what would stop the project — before anyone
spends money on it.

49 modules · 15,000+ lines · **899 tests** across 26 files.

Code and comments are in Italian: the domain is Italian law and Italian cadastral data,
and translating the terminology would make the regulatory references harder to verify,
not easier.

---

## The problem it actually solves

Most site-suitability tools answer *"where, in this region, is the terrain good?"* — a
raster of slope, irradiance and land cover, and a coloured map.

That question is already solved, and it is not the expensive one. The expensive question is:

> *These specific parcels — who owns them, what binds them, can they be connected, and what
> will an authority say?*

That is where projects die: a habitat designation, a landslide classification, a saturated
grid queue, an unresolved title. land-scout is built around that second question.

## The design principle

**A source that does not answer is not an absence of constraints.**

This sounds obvious and is the single most common failure in this class of tool. A WFS
endpoint returning HTTP 200 with an empty feature set, a service that was silently moved,
a provincial code that no longer resolves — each of these reads, downstream, as "no
constraint found", which is indistinguishable from "clean parcel" unless you build against it.

So every module distinguishes three states, never two:

| state | meaning |
|---|---|
| `False` | verified: the constraint is not there |
| `True` | verified: the constraint is there |
| `None` | **not verified** — the source did not answer, and the report says so |

A large share of the test suite exists to hold this line: one battery takes down every
external service one at a time and asserts the tool never reports "clean"; another asks
the harder question — what if the service *answers*, but with garbage?

Six test files are **not** in this repository (`qa_stress`, `qa_estremo`, `qa_adversarial`,
`qa_integrazione`, `qa_occupazione`, `qa_ispezione` — 236 assertions). They are pinned to
the real cadastral coordinates of the case study and check live answers at those exact
points: *this point is parcel 142 of sheet 70*, *this parcel is inside the SPA*. Without
the coordinates they prove nothing, and moving them elsewhere makes them fail, because at
the new location the constraint is not there. They run against the private tree. Every
coordinate in this repository has been shifted off the real site.

## What it checks

- **Cadastre** — parcels, geometry, area, ownership shares read from downloaded visure
- **Natura 2000** — SPA/SAC overlap, buffer distances, habitat types with absolute prohibitions
- **Landslide and flood risk** (PAI) — hazard classes, blocking vs. informational
- **Landscape constraints** — lake and river buffers, woodland, listed areas
- **Grid** — distance to substations and lines, connection queue saturation, provincial criticality
- **Terrain** — slope from 10 m DEM, aspect, ridge-line buffers, tree canopy
- **Suitable-area law** — Italian Legislative Decree 199/2021 art. 20 criteria
- **Administrative precedent** — how the competent authority has actually decided before

Then it aggregates: contiguous blocks, counterparty count, signatures required, portfolio
of independent non-overlapping blocks from the same pool.

## `taratura.py` — the module I am most attached to

The idea came from a wind-siting project that validates its suitability map against ~12,800
existing turbines: if the model says "excellent" where nobody ever built, the model is wrong.

Applied to the pilot area, the idea broke — and how it broke is the result:

- the 44 decided environmental-assessment cases were fences, houses, forestry works.
  **Zero energy installations.**
- the single rejection had no parcels listed, so it cannot be located on the map
- and the scoring engine had already derived its habitat rule *from that rejection* —
  validating against it would have been circular

With one negative out of 37 concluded cases, a model that always answered "approved" would
score 97% accuracy and know nothing. So the module does not report accuracy. It constrains
**how the number may be used**:

```python
T = taratura('Esempio', 'XX', tech='BESS')
T['tasso_positivo']    # 0.97  — always computed
T['tasso_spendibile']  # None  — not transferable: no case in the registry is an installation
```

and it splits arguments into what survives scrutiny and what does not:

```
DEFENSIBLE:  [observed] 32 of 44 cases fall inside the Natura 2000 site: the authority
             routinely processes applications there — the designation does not close
             the procedure upfront.
DO NOT SAY:  "97% get approved here, so ours will too" — none of those 44 cases is
             an energy installation.
```

A number that is true and not transferable is more dangerous than a missing one, because
it survives until someone checks.

## Install

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Linux/macOS: .venv/bin/pip
```

Python 3.12. Geometry via `shapely`, PDF parsing via `pymupdf`; the rest is standard library.

## Run

```bash
.venv/Scripts/python -m landscout.taratura Esempio XX --tech BESS
.venv/Scripts/python tests/run_all.py
```

## Status and limits

- Calibrated on a **pilot area in Campania**; the constraint layers are Italian and several
  are regional. Using it elsewhere in Italy means re-checking which regional endpoints exist.
- Several official endpoints are dead upstream (SITAP dismissed, others returning 403/404).
  Where a source is gone, the affected check is reported as *not verified* rather than passed.
- The price thresholds in `engine.py` and `config.py` are **placeholders**, not market
  guidance. Replace them with observed comparables for your own area.
- No data from the real deal it was built for is included in this repository. The example
  registry under `data/raw/precedenti/` is synthetic: it reproduces the statistical shape
  of a real one so the tests are meaningful, but every record in it is invented.

## Licence

AGPL-3.0. If you run a modified version as a network service, the modified source has to
be available to its users.
