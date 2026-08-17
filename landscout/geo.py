"""land-scout — GEO (v0.1, 16/07/2026): dove sta davvero questo punto.

Nasce da un bug di prodotto trovato in QA, non da un capriccio tecnico.

Il tool CHIEDEVA comune e provincia all'utente e poi si fidava. Tre conseguenze, tutte
viste sul campo:
  1. chi cliccava un punto sulla mappa senza compilare i campi -> crash oscuro;
  2. chi sbagliava provincia -> il dossier girava lo stesso, usando i layer regionali
     SBAGLIATI (coordinate campane + prov='MI' -> controlli Lombardia) e non lo diceva;
  3. campi obbligatori inutili: la provincia e' DEDUCIBILE dal punto.

Qui la ricaviamo da Nominatim (reverse geocoding), con cache e TTL lungo: i confini
amministrativi non cambiano quasi mai.

Regola ereditata da cache.py: **la cache non deve mai trasformare un errore in un dato**.
Se Nominatim non risponde, si ritorna un esito 'incerto' esplicito — non si inventa.

CLI:
  .venv/Scripts/python -m landscout.geo --lat 42.333 --lon 13.711
"""
import argparse, json, sys, urllib.parse, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass

from landscout.cache import JsonCache
from landscout.config import EP, PROV_REGIONE, norm_prov, valida_coordinate, CoordinataNonValida

UA = {'User-Agent': 'land-scout/0.1 (screening terreni rinnovabili)'}

# Nominatim restituisce il nome esteso della provincia ("Provincia di Benevento"),
# non la sigla. Serve la mappa inversa. ISO3166-2-lvl6 quando c'e' e' piu' affidabile.
_REGIONI = set(PROV_REGIONE.values())


def _sigla_da_address(addr):
    """Estrae la sigla provincia dall'oggetto address di Nominatim."""
    iso = addr.get('ISO3166-2-lvl6') or ''          # es. 'IT-BN'
    if iso.startswith('IT-') and len(iso) == 5:
        s = iso[3:].upper()
        if s in PROV_REGIONE:
            return s
    # fallback: match sul nome della provincia/citta' metropolitana
    testo = ' '.join(str(addr.get(k, '')) for k in ('county', 'state_district', 'province', 'city'))
    for sigla in PROV_REGIONE:
        if f'IT-{sigla}' in testo.upper():
            return sigla
    return None


def localizza(lat, lon, cache=None):
    """(lat, lon) -> {'comune', 'prov', 'regione', 'certo': bool, 'nota'}.

    Alza CoordinataNonValida se il punto non e' un punto italiano plausibile.
    Non alza se Nominatim e' irraggiungibile: ritorna certo=False (il chiamante decide).
    """
    lat, lon = valida_coordinate(lat, lon)
    cache = cache or JsonCache('geocode')
    key = f'rev|{lat:.5f}|{lon:.5f}'
    v = cache.get(key, '__miss__')
    if v != '__miss__' and v is not None:
        return v
    try:
        q = urllib.parse.urlencode({'lat': lat, 'lon': lon, 'format': 'jsonv2',
                                    'zoom': 10, 'addressdetails': 1})
        r = json.loads(urllib.request.urlopen(urllib.request.Request(
            EP['nominatim_reverse'] + '?' + q, headers=UA), timeout=25).read().decode('utf-8'))
    except Exception as e:
        # NON si mette in cache: un errore di rete non e' un dato (cfr. cache.py)
        return {'comune': None, 'prov': None, 'regione': None, 'certo': False,
                'nota': f'geocoding non raggiungibile ({type(e).__name__}): comune/provincia non determinati'}

    addr = (r or {}).get('address') or {}
    if (addr.get('country_code') or '').upper() != 'IT':
        paese = addr.get('country') or 'paese sconosciuto'
        raise CoordinataNonValida(
            f'il punto ({lat}, {lon}) e\' in {paese}, non in Italia: '
            'land-scout usa solo cartografia italiana')

    comune = addr.get('city') or addr.get('town') or addr.get('village') or addr.get('municipality')
    prov = _sigla_da_address(addr)
    out = {'comune': comune, 'prov': prov,
           'regione': PROV_REGIONE.get(prov) if prov else None,
           'certo': bool(comune and prov),
           'nota': 'da reverse geocoding OpenStreetMap/Nominatim'}
    if not out['certo']:
        out['nota'] = ('punto in Italia ma senza comune/provincia riconoscibili '
                       '(probabile mare, lago o area senza confini amministrativi)')
    if out['certo']:
        cache.set(key, out)          # in cache SOLO gli esiti certi
        cache.flush()
    return out


def risolvi(lat, lon, comune=None, prov=None, cache=None):
    """Concilia quello che dice l'utente con quello che dice la mappa.

    Ritorna (comune, prov, avvisi[]). La mappa VINCE sempre sull'utente quando sono in
    conflitto: le coordinate sono il dato duro, i campi sono digitati a mano.
    """
    avvisi = []
    prov_utente = norm_prov(prov) or None
    loc = localizza(lat, lon, cache=cache)

    if not loc['certo']:
        if not (comune and prov_utente):
            raise CoordinataNonValida(
                f"{loc['nota']}. Indica comune e provincia a mano, oppure sposta il punto.")
        avvisi.append(f"provincia non verificata sulla mappa ({loc['nota']}): uso quella indicata ({prov_utente})")
        return comune, prov_utente, avvisi

    if prov_utente and prov_utente != loc['prov']:
        avvisi.append(
            f"provincia corretta: hai indicato {prov_utente} ma il punto ({lat:.5f}, {lon:.5f}) "
            f"e' in provincia di {loc['prov']} ({loc['comune']}). Uso {loc['prov']}: i controlli "
            f"su vincoli e paesaggio sono REGIONALI e con {prov_utente} sarebbero stati sbagliati.")
    if comune and loc['comune'] and comune.strip().lower() != loc['comune'].strip().lower():
        avvisi.append(f"comune corretto: hai scritto \"{comune}\" ma il punto e' in \"{loc['comune']}\"")
    return loc['comune'], loc['prov'], avvisi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lat', type=float, required=True)
    ap.add_argument('--lon', type=float, required=True)
    ap.add_argument('--comune'); ap.add_argument('--prov')
    A = ap.parse_args()
    try:
        print(json.dumps(localizza(A.lat, A.lon), ensure_ascii=False, indent=1))
        if A.comune or A.prov:
            c, p, av = risolvi(A.lat, A.lon, A.comune, A.prov)
            print(f'\nrisolto -> {c} ({p})')
            for a in av:
                print('  ⚠', a)
    except CoordinataNonValida as e:
        print('✗ coordinata non valida:', e); sys.exit(2)


if __name__ == '__main__':
    main()
