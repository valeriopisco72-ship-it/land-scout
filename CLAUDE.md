# land-scout — note per Claude

Screening di particelle catastali italiane per rinnovabili (agriPV, FV, BESS):
vincoli (Natura 2000, habitat, PAI, SITAP), rete, blocchi contigui, valore.
Codice e commenti in **italiano**: il dominio e' diritto e catasto italiano.

## Ambiente

- Python **3.12** (numpy 2.5 non esiste per 3.11):
  `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- Suite completa (un solo esito, exit 1 se anche un test fallisce):
  `.venv/bin/python tests/run_all.py [-q]` — ~3,5 minuti, gira **offline**.
- Un file solo: `.venv/bin/python tests/qa_<nome>.py`.
- I servizi esterni (EEA, IdroGEO, SITAP, catasto AdE, Overpass, PVGIS) spesso
  non sono raggiungibili dal container: i test li sostituiscono con risposte finte
  (`V.get = ...`, `scan.get = ...`). Non aggiungere test che dipendono dalla rete.

## La regola che non si tocca: tre stati, mai due

| valore | significato |
|---|---|
| `False` / `0` / `-1` | verificato: il vincolo NON c'e' |
| `True` / numero | verificato: il vincolo c'e' |
| `None` (o chiave assente) | **NON verificato** — la fonte non ha risposto |

Il bug piu' frequente del progetto e' un `None` riscritto come `0`/`False` da un
modulo a valle (`.get(k, 0)`, `bool(x)`, `x or 0`, `if not x`). Prima di scrivere
un default su un campo di VINCOLO chiediti se significa "verificato pulito". Le
DISTANZE usano la sentinella `9e9` ("nessun elemento trovato"): non stamparla come
misura (`engine._distanza`).

Catena tipica: `vincoli.feasibility` -> `vincoli.to_score_fields` ->
`engine.score_parcel` -> `recommend` / `dossier` / `valore` / `blocco`.
`forbice.py` misura quanto un voto dipende dai controlli mancanti.

## Stile dei test

- Ogni file `tests/qa_*.py` e' uno script: `t(nome, cond, dettaglio, grave=)`,
  riepilogo finale `RISULTATO: X/Y pass` (lo legge `run_all.py`), `sys.exit(1)` se FAIL.
- Ogni verifica ha la sua **controprova** (con la fonte che risponde, nessun avviso
  inventato). Un test deve poter fallire: verificarlo rosso prima della correzione.
- Nuovo modulo = nuovo `qa_<modulo>.py`; `run_all.py` lo trova da solo.

## Stile del codice

- Le correzioni importanti portano un commento datato `# ⚠ GG/MM/AAAA: ...` che
  spiega cosa succedeva prima e perche' era pericoloso: e' la memoria del progetto.
- Endpoint, soglie e mappe provincia/regione stanno in `landscout/config.py`.
- Mai committare dati reali (visure, catasto, cache, output di run): vedi `.gitignore`.
  Le coordinate nel repo sono spostate dal sito reale.
