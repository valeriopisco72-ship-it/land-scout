"""land-scout — modulo ALERT (v0.1, 15/07/2026): monitoraggio dei terreni sotto osservazione.

PERCHE' ESISTE (modello di business)
Il report one-shot monetizza male: il proprietario paga una volta e sparisce. L'alert
trasforma il tool in un **servizio ricorrente** (abbonamento) — ed e' ricavo *legalmente
pulito*: si vende informazione/monitoraggio, NON si mette in contatto nessuno
(cfr. Cass. SS.UU. 19161/2017: la % sul deal immobiliare senza abilitazione = mediazione).

COSA SORVEGLIA (diff tra due esecuzioni)
  - nuovi progetti VIA vicino al terreno  -> "un developer si sta muovendo a X km da te"
  - progetti spariti/cambiati di categoria
  - cambi nel registro rete (code del nodo)
Il censimento si aggiorna con `-m landscout.via --build`; poi `-m landscout.alert --check`
confronta con l'ultimo snapshot e dice **cosa e' cambiato**.

CLI:
  .venv/Scripts/python -m landscout.alert --add casa --comune Morcone --prov BN --lat 42.333 --lon 13.711 --raggio 25
  .venv/Scripts/python -m landscout.alert --lista
  .venv/Scripts/python -m landscout.alert --check          # primo giro = baseline, poi segnala le novita'
"""
import argparse, csv, json, math, sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass
from landscout.config import RAW, CACHE_DIR, CENSUS
from landscout.match import comuni_of, norm_tech, geocode, load_cache, save_cache, km, resolve_known
from landscout.rete import nodo as nodo_info

WATCH = RAW / 'alert' / 'watchlist.json'
SNAP = CACHE_DIR / 'alert_snapshot.json'


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except Exception:
        return default


def _save(p, d):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')


# ---------- watchlist ----------
def aggiungi(nome, comune, prov, lat, lon, raggio_km=25, tech=None):
    w = _load(WATCH, {})
    w[nome] = {'comune': comune, 'prov': prov, 'lat': lat, 'lon': lon,
               'raggio_km': raggio_km, 'tech': tech, 'dal': str(date.today())}
    _save(WATCH, w)
    return w[nome]


def lista():
    return _load(WATCH, {})


# ---------- scansione: progetti VIA vicini a un terreno sorvegliato ----------
def progetti_vicini(w, cache):
    """Ritorna {chiave_progetto: info} entro il raggio dal terreno sorvegliato."""
    out = {}
    if not Path(CENSUS).exists():
        return out
    with open(CENSUS, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f, delimiter=';'):
            prop = (r.get('proponente') or '').strip()
            if not prop:
                continue
            tech = norm_tech(r.get('categoria'))
            if w.get('tech') and tech != w['tech']:
                continue
            prog = r.get('progetto') or ''
            comuni = comuni_of(prog)
            # distanza: stesso comune = 0, altrimenti geocoding dei comuni del progetto
            d = None
            if any((w['comune'] or '').lower() == c.lower() for c in comuni):
                d = 0.0
            else:
                if (r.get('prov') or '').upper() != (w['prov'] or '').upper():
                    continue          # fuori provincia: salta (evita migliaia di geocoding)
                ds = [km([w['lat'], w['lon']], geocode(c, r.get('prov', ''), cache)) for c in comuni]
                ds = [x for x in ds if x is not None]
                if ds:
                    d = min(ds)
            if d is None or d > w.get('raggio_km', 25):
                continue
            key = f"{prop.lower()}|{' '.join(prog.split())[:60].lower()}"
            out[key] = {'proponente': prop, 'tech': tech, 'km': round(d, 1),
                        'mw': r.get('MW', ''), 'comuni': comuni[:3], 'link': r.get('link', '')}
    return out


# ---------- check ----------
def check(verbose=True):
    w_all = lista()
    if not w_all:
        print('watchlist vuota: aggiungi un terreno con --add'); return []
    snap = _load(SNAP, {})
    cache = load_cache()
    eventi = []
    for nome, w in w_all.items():
        vicini = progetti_vicini(w, cache)
        prima = snap.get(nome, {}).get('progetti', {})
        primo_giro = nome not in snap
        nuovi = {k: v for k, v in vicini.items() if k not in prima}
        spariti = [k for k in prima if k not in vicini]
        # rete
        nodo = nodo_info(w['comune'], w['prov'])
        rete_prima = snap.get(nome, {}).get('rete_hash')
        rete_ora = json.dumps({k: nodo.get(k) for k in ('pv_queue_mw', 'bess_queue_mw', 'wind_queue_mw', 'data')},
                              sort_keys=True)
        if primo_giro:
            eventi.append({'watch': nome, 'tipo': 'BASELINE',
                           'msg': f"baseline creata: {len(vicini)} progetti entro {w['raggio_km']} km"})
        else:
            for k, v in nuovi.items():
                gruppo = resolve_known(v['proponente'], '')
                chi = gruppo[0] if gruppo else v['proponente']
                eventi.append({'watch': nome, 'tipo': 'NUOVO_PROGETTO', 'km': v['km'],
                               'msg': f"🔔 nuovo progetto {v['tech']} a {v['km']} km: {chi}"
                                      + (f" ({v['mw']} MW)" if v['mw'] else ''),
                               'link': v['link']})
            for k in spariti:
                eventi.append({'watch': nome, 'tipo': 'PROGETTO_RIMOSSO',
                               'msg': f"progetto non piu' presente nel censimento: {prima[k]['proponente']}"})
            if rete_prima and rete_prima != rete_ora:
                eventi.append({'watch': nome, 'tipo': 'RETE_CAMBIATA',
                               'msg': f"⚡ cambiato il registro rete del nodo {w['comune']}"})
        snap[nome] = {'progetti': vicini, 'rete_hash': rete_ora, 'ultimo_check': str(date.today())}
    save_cache(cache)
    _save(SNAP, snap)
    if verbose:
        stampa(eventi)
    return eventi


def stampa(eventi):
    print('=' * 76)
    print(f'  ALERT — {date.today()}')
    print('=' * 76)
    if not eventi:
        print('  nessuna novita\' dai terreni sorvegliati.')
    for e in eventi:
        print(f"  [{e['watch']}] {e['msg']}")
        if e.get('link'):
            print(f"      {e['link']}")
    print('=' * 76)
    print('  Aggiorna prima il censimento con:  python -m landscout.via --build')
    print('  Ricavo ricorrente = monitoraggio (informazione), NON % sul deal: niente mediazione.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--add'); ap.add_argument('--comune'); ap.add_argument('--prov')  # no default='BN' (QA 16/07)
    ap.add_argument('--lat', type=float); ap.add_argument('--lon', type=float)
    ap.add_argument('--raggio', type=float, default=25); ap.add_argument('--tech')
    ap.add_argument('--lista', action='store_true'); ap.add_argument('--check', action='store_true')
    A = ap.parse_args()
    if A.add:
        if not (A.comune and A.lat and A.lon):
            print('serve --comune --lat --lon'); return
        v = aggiungi(A.add, A.comune, A.prov, A.lat, A.lon, A.raggio, A.tech)
        print(f'aggiunto "{A.add}":', v); return
    if A.lista:
        w = lista()
        print(f'watchlist: {len(w)} terreni sorvegliati')
        for k, v in w.items():
            print(f"  - {k}: {v['comune']} ({v['prov']}) raggio {v['raggio_km']} km"
                  + (f" · solo {v['tech']}" if v.get('tech') else '') + f" · dal {v['dal']}")
        return
    if A.check:
        check(); return
    print('Uso: --add <nome> --comune .. --lat .. --lon .. [--raggio 25] [--tech agriPV] | --lista | --check')


if __name__ == '__main__':
    main()
