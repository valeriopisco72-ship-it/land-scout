"""land-scout — API (v0.1, 15/07/2026): il motore esposto come servizio web.

Perche' asincrona: un dossier richiede ~1 minuto (overlay vincoli + PVGIS + Overpass +
censimento). In HTTP non si puo' bloccare: POST crea un job, GET ne legge lo stato.

Endpoint:
  GET  /                        -> la pagina web (form + mappa + dossier)
  POST /api/dossier             -> {comune, prov, ha, lat, lon | parcels} -> {job_id}
  GET  /api/dossier/{job_id}    -> {stato, progresso, risultato|errore}
  GET  /api/copertura/{prov}    -> cosa si puo' davvero verificare in quella provincia
  GET  /api/health

Avvio:
  .venv/Scripts/python -m landscout.api          (poi apri http://127.0.0.1:8000)
"""
import sys, threading, time, traceback, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from landscout.config import copertura, info as config_info, norm_prov, CoordinataNonValida
from landscout.dossier import build_dossier
from landscout.geo import localizza

app = FastAPI(title='land-scout', version='0.1',
              description='Screening terreni per rinnovabili: fattibilità, tecnologia, resa, valore, aziende.')

JOBS: Dict[str, Dict[str, Any]] = {}       # in-memory: sufficiente per l'MVP mono-processo
WEB = Path(__file__).resolve().parent / 'web' / 'index.html'

# ⚠ QA 16/07: JOBS non veniva mai svuotato. Ogni dossier (risultato completo, decine di KB)
# restava in memoria per sempre -> il processo cresce finche' non muore. Su un MVP locale
# passa inosservato; su una pagina pubblica e' il primo modo in cui il sito cade.
MAX_JOBS = 200          # tetto duro: oltre, si buttano i piu' vecchi
JOB_TTL = 3600.0        # un dossier consultabile per un'ora: poi si rifa'
_JOBS_LOCK = threading.Lock()


def _pulisci_jobs():
    """Toglie i job scaduti e, se restano troppi, i piu' vecchi. Chiamata a ogni creazione."""
    with _JOBS_LOCK:
        ora = time.time()
        for jid in [k for k, v in JOBS.items()
                    if ora - v.get('_t', ora) > JOB_TTL and v.get('stato') in ('completato', 'errore')]:
            JOBS.pop(jid, None)
        if len(JOBS) > MAX_JOBS:
            # i job ancora in corso non si buttano: si scartano i piu' vecchi fra i conclusi
            conclusi = sorted((v.get('_t', 0), k) for k, v in JOBS.items()
                              if v.get('stato') in ('completato', 'errore'))
            for _, jid in conclusi[:len(JOBS) - MAX_JOBS]:
                JOBS.pop(jid, None)


class RichiestaDossier(BaseModel):
    # comune/prov sono OPZIONALI: si ricavano dal punto (reverse geocoding). Prima erano
    # obbligatori e chi cliccava sulla mappa senza compilarli otteneva un crash; peggio,
    # chi sbagliava provincia otteneva un dossier costruito sui layer regionali sbagliati.
    comune: Optional[str] = Field(None, examples=['Morcone'],
                                  description='opzionale: se assente si ricava dalle coordinate')
    prov: Optional[str] = Field(None, min_length=2, max_length=4, examples=['BN'],
                                description='opzionale: se assente si ricava dalle coordinate')
    lat: Optional[float] = None
    lon: Optional[float] = None
    ha: Optional[float] = Field(None, description='ettari totali se si passa un solo punto')
    parcels: Optional[Dict[str, Dict[str, Any]]] = Field(None, description='{id:{lat,lon,ha}} alternativo a lat/lon/ha')
    tech: Optional[str] = Field(None, examples=['agriPV'])
    geo: bool = Field(False, description='geocoding dei comuni per i km (piu\' lento)')


def _esegui(job_id: str, r: RichiestaDossier):
    try:
        JOBS[job_id]['stato'] = 'in_corso'
        JOBS[job_id]['progresso'] = 'analisi vincoli, resa, rete e aziende...'
        parcels = r.parcels or {'p1': {'lat': r.lat, 'lon': r.lon, 'ha': r.ha}}
        d = build_dossier(parcels, r.comune, norm_prov(r.prov) or None, tech=r.tech, geo=r.geo)
        JOBS[job_id].update({'stato': 'completato', 'risultato': d, 'progresso': 'fatto'})
    except (CoordinataNonValida, ValueError) as e:
        # errore d'uso, non un guasto: messaggio leggibile, niente traceback in faccia all'utente
        JOBS[job_id].update({'stato': 'errore', 'errore': str(e), 'tipo': 'input'})
    except Exception as e:
        JOBS[job_id].update({'stato': 'errore', 'tipo': 'interno',
                             'errore': f'errore interno ({type(e).__name__}): {e}',
                             'traceback': traceback.format_exc()[-800:]})


@app.get('/', response_class=HTMLResponse)
def home():
    if WEB.exists():
        return WEB.read_text(encoding='utf-8')
    return '<h1>land-scout</h1><p>pagina web non trovata: manca landscout/web/index.html</p>'


@app.get('/api/health')
def health():
    return {'ok': True, 'config': config_info()}


@app.get('/api/copertura/{prov}')
def api_copertura(prov: str):
    c = copertura(prov)
    if not c.get('regione'):
        raise HTTPException(404, f'provincia "{prov}" non riconosciuta')
    return c


@app.get('/api/localizza')
def api_localizza(lat: float, lon: float):
    """Dove sta questo punto: comune, provincia, regione + cosa si puo' verificare li'.
    La pagina la chiama appena l'utente clicca sulla mappa: cosi' i campi si riempiono
    da soli e non c'e' modo di sbagliare provincia."""
    try:
        loc = localizza(lat, lon)
    except CoordinataNonValida as e:
        raise HTTPException(400, str(e))
    if loc.get('prov'):
        loc['copertura'] = copertura(loc['prov'])
    return loc


@app.post('/api/dossier')
def crea_dossier(r: RichiestaDossier):
    if not r.parcels and (r.lat is None or r.lon is None or r.ha is None):
        raise HTTPException(400, 'servono lat, lon e ha (oppure parcels)')
    # la provincia e' opzionale, ma se c'e' dev'essere vera (poi le coordinate hanno l'ultima parola)
    if r.prov and not copertura(r.prov).get('regione'):
        raise HTTPException(400, f'provincia "{r.prov}" non riconosciuta: serve una sigla valida '
                                 '(es. BN) — oppure lasciala vuota e la ricavo dal punto')
    if not r.parcels:
        try:
            from landscout.config import valida_coordinate
            valida_coordinate(r.lat, r.lon)
        except CoordinataNonValida as e:
            raise HTTPException(400, str(e))
        if r.ha is None or r.ha <= 0:
            raise HTTPException(400, f'superficie non valida ({r.ha}): servono ettari > 0')
    _pulisci_jobs()
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {'stato': 'in_coda', 'progresso': 'in coda', 'richiesta': r.model_dump(),
                    '_t': time.time()}
    threading.Thread(target=_esegui, args=(job_id, r), daemon=True).start()
    return {'job_id': job_id, 'stato': 'in_coda'}


@app.get('/api/dossier/{job_id}')
def leggi_dossier(job_id: str):
    j = JOBS.get(job_id)
    if not j:
        raise HTTPException(404, 'job inesistente')
    return JSONResponse(j)


def main():
    import uvicorn
    print('land-scout API  ->  http://127.0.0.1:8000')
    uvicorn.run(app, host='127.0.0.1', port=8000, log_level='warning')


if __name__ == '__main__':
    main()
