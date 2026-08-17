"""land-scout — modulo MATCH (v0.1, 15/07/2026): aziende da contattare per un terreno.

Dato un terreno (comune + coordinate + tecnologia consigliata), restituisce le
aziende migliori da contattare, ordinate per:
  1. PROSSIMITA' geografica  (progetti VIA reali vicino alle particelle)
  2. FIT TECNOLOGICO         (chi fa gia' la tecnologia adatta al terreno)
  3. INTERESSE DICHIARATO    (contatti gia' agganciati / focus sulla zona)

Fonte: censimento portale VIA nazionale (proponente, MW, comuni, tecnologia, link)
arricchito con la rubrica dei contatti reali (SPV -> gruppo -> persona d'ingresso).

CLI:
  .venv/Scripts/python -m landscout.match --comune Morcone --lat 42.333 --lon 13.711 --tech agriPV
  .venv/Scripts/python -m landscout.match --parcels <{id:{lat,lon,ha}}.json> --tech agriPV
"""
import argparse, csv, json, math, os, re, sys, urllib.parse, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass
from landscout.config import CENSUS, EP, UA, TIMEOUT
from landscout.cache import JsonCache

CENSUS_DEFAULT = str(CENSUS)

# categoria censimento VIA -> tecnologia normalizzata
def norm_tech(cat):
    c = (cat or '').upper()
    if 'AGRIV' in c or 'AGROV' in c: return 'agriPV'
    if 'FOTOVOLT' in c or c == 'FV': return 'PV'
    if 'ACCUMULO' in c or 'BESS' in c or 'STORAGE' in c: return 'BESS'
    if 'EOLIC' in c or 'WIND' in c: return 'wind'
    if 'IBRID' in c: return 'ibrido'
    return c.lower() or '?'

# tecnologie "affini" (fit parziale)
AFFINI = {'agriPV': {'PV', 'ibrido'}, 'PV': {'agriPV', 'ibrido'},
          'BESS': {'ibrido'}, 'wind': {'ibrido'}}

# --- RUBRICA CONTATTI REALI (editabile) — chiave = sottostringa nel nome proponente/progetto ---
# valore: (gruppo reale, persona d'ingresso, nota/stato)
KNOWN = [
    ('APOLLOSA',      ('MET Group / Keppel MET Renewables', 'Luca Villanova / Marco Albergucci', 'gemello autorizzato agriPV 44 MW in BN — invito LinkedIn in corso')),
    ('KEPPEL',        ('MET Group / Keppel MET Renewables', 'Luca Villanova', 'portafoglio 200 MWp Sud Italia')),
    ('WEB',           ('W.E.B. Windenergie (WEB Italia)', 'Andrea Tisot (CEO Italia) / Rainer Karan (MD)', 'INVITO inviato 15/07; 7 progetti in Irpinia')),
    ('ABEI',          ('ABEI Energy', 'contatto attuale da ritrovare', 'canale Vertone CHIUSO (ha lasciato ABEI)')),
    ('CSPV LACEDONIA',('ABEI Energy', 'contatto attuale da ritrovare', 'CSPV Lacedonia 34 MW AV')),
    ('SINERGIA GP',   ('Sinergia GP (developer seriale, Napoli)', 'visura camerale per nome', 'serie GP1-12; agriPV Amorosi 28 MW = molto vicino')),
    ('FRANCAVILLA',   ('SPV (capogruppo da visura)', 'visura camerale', 'agriPV 48 MW Comune di Benevento')),
    ('ARIANO SOLAR',  ('SPV (capogruppo da visura)', 'visura camerale', 'agriPV 65 MW AV')),
    ('OLIVOLA',       ('RWE Renewables Italia', '', r'RWE ha FV Olivola 78 MW in BN')),
    ('RWE',           ('RWE Renewables Italia', '', r'ha sviluppato Morcone/Acquafredda A-Z')),
    ('W.E.B',         ('W.E.B. Windenergie (WEB Italia)', 'Andrea Tisot / Rainer Karan', 'INVITO inviato 15/07')),
]
# contatti attivi non necessariamente nel censimento VIA (pipeline outreach) — bonus interesse dichiarato
INTERESSE_ZONA = {
    'MET Group / Keppel MET Renewables': 'gemello 44 MW in BN',
    'W.E.B. Windenergie (WEB Italia)': 'radicata in Irpinia',
    'RWE Renewables Italia': 'impianti operativi nella zona',
}

def resolve_known(proponente, progetto):
    s = (proponente + ' ' + progetto).upper()
    for key, val in KNOWN:
        if key in s:
            return val
    return None

# ---------- geocoding comuni (Nominatim, cache con TTL, graceful) ----------
def load_cache():
    return JsonCache('geocode')            # cache unica con TTL (landscout.cache)
def save_cache(c):
    c.flush()
def geocode(comune, prov, cache):
    key = f'{comune}|{prov}'
    v = cache.get(key, '__miss__')
    if v != '__miss__':
        return v
    try:
        q = urllib.parse.urlencode({'q': f'{comune}, {prov}, Italia', 'format': 'json', 'limit': 1})
        r = json.loads(urllib.request.urlopen(urllib.request.Request(
            EP['nominatim'] + '?' + q, headers=UA), timeout=25).read().decode('utf-8'))
        v = [float(r[0]['lat']), float(r[0]['lon'])] if r else None
    except Exception:
        v = None
    cache.set(key, v)
    return v
def km(a, b):
    if not a or not b: return None
    dlat = (a[0]-b[0])*111.32; dlon = (a[1]-b[1])*111.32*math.cos(math.radians(a[0]))
    return math.hypot(dlat, dlon)

# ---------- estrai comuni dal testo progetto ----------
def comuni_of(progetto):
    out = []
    for m in re.finditer(r'[Cc]omun[ei]\s+di\s+([^().;]+)', progetto):
        seg = m.group(1)
        for part in re.split(r',|\se\s', seg):
            name = part.strip().strip('"').strip()
            if name and len(name) < 40 and name[0].isupper():
                out.append(name)
    return list(dict.fromkeys(out))[:6]

# ---------- core ----------
def match_companies(target_comune, target_prov, target_latlon, target_tech, census=CENSUS_DEFAULT, geo=True):
    cache = load_cache() if geo else {}
    rows = list(csv.DictReader(open(census, encoding='utf-8-sig'), delimiter=';'))
    scored = []
    for r in rows:
        prop = (r.get('proponente') or '').strip()
        if not prop: continue
        tech = norm_tech(r.get('categoria'))
        prog = r.get('progetto') or ''
        comuni = comuni_of(prog)
        # --- prossimita' ---
        prox = 0; dist = None; why_geo = ''
        same = any(target_comune and target_comune.lower() == c.lower() for c in comuni)
        if same:
            prox = 100; why_geo = f'stesso comune ({target_comune})'
        elif r.get('prov') and target_prov and r['prov'].upper() == target_prov.upper():
            prox = 40; why_geo = f'stessa provincia ({target_prov})'
        if geo and target_latlon and comuni:
            ds = [km(target_latlon, geocode(c, r.get('prov', ''), cache)) for c in comuni]
            ds = [d for d in ds if d is not None]
            if ds:
                dist = min(ds)
                prox = max(prox, int(max(0, 90 - dist)))  # piu' vicino = piu' punti
                why_geo = f'~{dist:.0f} km'
        # --- fit tecnologico ---
        tfit = 0; why_tech = tech
        if target_tech:
            if tech == target_tech: tfit = 40; why_tech = f'{tech} (match)'
            elif tech in AFFINI.get(target_tech, set()): tfit = 15; why_tech = f'{tech} (affine)'
            else: tfit = 0
        else:
            tfit = 20
        # --- interesse dichiarato / contatto noto ---
        known = resolve_known(prop, prog); kbonus = 0
        if known:
            kbonus = 30
            if known[0] in INTERESSE_ZONA: kbonus += 20
        score = prox + tfit + kbonus
        try: mw = float(r.get('MW') or 0)
        except Exception: mw = 0
        scored.append({'proponente': prop, 'tech': tech, 'mw': mw, 'comuni': comuni,
                       'dist_km': round(dist, 1) if dist else None, 'why_geo': why_geo,
                       'why_tech': why_tech, 'score': score, 'known': known, 'link': r.get('link', '')})
    if geo: save_cache(cache)
    # dedup per gruppo/proponente (tieni il migliore, conta i progetti)
    best = {}
    for s in scored:
        gid = s['known'][0] if s['known'] else s['proponente']
        if gid not in best or s['score'] > best[gid]['score']:
            s = dict(s); s['n_progetti'] = 1; s['gid'] = gid; best[gid] = s
        else:
            best[gid]['n_progetti'] = best[gid].get('n_progetti', 1) + 1
    out = sorted(best.values(), key=lambda x: -x['score'])
    return out

def print_report(out, target_comune, target_tech, top=12):
    print('=' * 92)
    print(f'  AZIENDE DA CONTATTARE — terreno in {target_comune or "?"} · tecnologia consigliata: {target_tech or "qualsiasi"}')
    print('=' * 92)
    for i, s in enumerate(out[:top], 1):
        head = s['known'][0] if s['known'] else s['proponente']
        print(f'\n{i}. {head}   [score {s["score"]}]')
        if s['known']:
            print(f'   -> entry point: {s["known"][1]}  ·  {s["known"][2]}')
            if head != s['proponente']:
                print(f'   -> progetto VIA a nome: {s["proponente"]}')
        why = ' · '.join(x for x in (s['why_geo'], s['why_tech'], f'{s["mw"]:.0f} MW' if s['mw'] else '') if x)
        print(f'   {why}' + (f'  ·  +{s["n_progetti"]-1} altri progetti in zona' if s.get('n_progetti', 1) > 1 else ''))
        if s['comuni']: print(f'   comuni: {", ".join(s["comuni"])}')
        if s['link']: print(f'   VIA: {s["link"]}')
    print('\n' + '=' * 92)
    print('  NB: proponenti "SPV" = societa'+"'"+' veicolo → visura camerale (~7€) per il gruppo reale.')
    print('      "entry point" = contatto/gruppo dalla rubrica land-scout (aggiornare KNOWN nel modulo).')
    print('=' * 92)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--comune'); ap.add_argument('--prov')   # niente default='BN' (bug QA 16/07)
    ap.add_argument('--lat', type=float); ap.add_argument('--lon', type=float)
    ap.add_argument('--tech', help='agriPV | PV | BESS | wind (dalla raccomandazione)')
    ap.add_argument('--parcels', help='JSON {id:{lat,lon,ha}} — usa il centroide')
    ap.add_argument('--census', default=CENSUS_DEFAULT)
    ap.add_argument('--no-geo', action='store_true', help='salta il geocoding (solo comune/provincia)')
    ap.add_argument('--out')
    A = ap.parse_args()
    latlon = None
    if A.parcels:
        p = json.load(open(A.parcels, encoding='utf-8'))
        la = sum(v['lat'] for v in p.values()) / len(p); lo = sum(v['lon'] for v in p.values()) / len(p)
        latlon = [la, lo]
    elif A.lat and A.lon:
        latlon = [A.lat, A.lon]
    out = match_companies(A.comune, A.prov, latlon, A.tech, census=A.census, geo=not A.no_geo)
    print_report(out, A.comune, A.tech)
    if A.out:
        json.dump(out, open(A.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('salvato:', A.out)

if __name__ == '__main__':
    main()
