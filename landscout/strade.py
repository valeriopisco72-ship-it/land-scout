"""land-scout strade — la viabilita' che attraversa il blocco.

Trovato da Valerio guardando la mappa satellitare del blocco F: *"in quei terreni
mi sembra che ci siano delle strade che li attraversano"*. Aveva ragione — e il
tool non le misurava. Stessa classe di problema dei fabbricati: il catasto
descrive la PROPRIETA', non l'uso del suolo.

Due effetti, molto diversi fra loro:

1. **La sede stradale non e' installabile.** In ettari e' poco (0,7% del blocco
   Morcone), ma su Fg83/14 vale il 12% della particella.
2. **Una strada che ATTRAVERSA spezza il blocco in due.** Questo conta molto piu'
   degli ettari persi: due mezzi campi separati da una carraia non sono un
   campo. Si vede solo sottraendo la sede stradale dalla maschera *prima*
   dell'erosione (vedi `installabile.analizza(..., strade=...)`).

Quello che invece NON si fa e' penalizzare la vicinanza a una strada:

- Le **fasce di rispetto stradale** (DM 1404/1968, art. 26 Reg. CdS) riguardano
  le COSTRUZIONI. I moduli agrivoltaici non lo sono pacificamente, la materia e'
  controversa e varia per ente gestore: il tool **segnala e non decide**.
- Le **aree adiacenti alla rete AUTOSTRADALE entro 300 m** sono espressamente
  **aree idonee** (art. 20 c.8 lett. c-ter D.Lgs 199/2021): li' la strada e' un
  vantaggio, non un problema. Attenzione: vale per le autostrade, non per ogni
  strada — a Morcone la Fondo Valle Tammaro non e' autostrada.
- Per **recinzioni oltre 1 m** servono 3 m dal confine stradale (art. 26 c.8
  Reg. CdS): riguarda il layout, non l'idoneita'.

Uso:
    from landscout import strade
    S = strade.scarica(bbox)                       # OSM Overpass
    occ = strade.occupazione(particelle, S)        # % di sede stradale
    m = strade.maschera(particelle, S)             # da passare a installabile
"""
import json
import math
import urllib.parse
import urllib.request

import numpy as np
from PIL import Image, ImageDraw

# Piu' istanze: l'endpoint principale risponde 429/504 con facilita' sui bbox
# grandi, e restituire una lista vuota significherebbe dichiarare "nessuna
# strada" quando la verita' e' "non ho guardato".
OVERPASS = ['https://overpass-api.de/api/interpreter',
            'https://overpass.kumi.systems/api/interpreter',
            'https://overpass.private.coffee/api/interpreter']

# Larghezza tipica della sede (carreggiata + banchine) per classe OSM, in metri.
# Sovrastimare qui e' prudente: toglie ettari, non ne inventa.
LARGHEZZA_M = {
    'motorway': 25.0, 'motorway_link': 12.0, 'trunk': 14.0, 'trunk_link': 10.0,
    'primary': 10.0, 'primary_link': 8.0, 'secondary': 9.0, 'secondary_link': 7.0,
    'tertiary': 7.0, 'tertiary_link': 6.0, 'unclassified': 5.0, 'residential': 5.0,
    'living_street': 5.0, 'service': 4.0, 'track': 3.5, 'path': 2.0,
    'footway': 2.0, 'cycleway': 2.5, 'bridleway': 2.0,
}
# Sotto questa classe la "strada" e' un sentiero: non spezza un campo arato.
IGNORA = {'footway', 'path', 'cycleway', 'bridleway', 'steps'}

# ⚠ Le FERROVIE non sono `highway`: con la sola query sulle strade una linea
# ferroviaria e' invisibile, e un fondo che le corre a fianco passa tutti i
# filtri. Sono infrastrutture lineari esattamente come le strade — spezzano il
# campo, hanno una fascia di rispetto e non sono edificabili — quindi entrano
# nello stesso scarico. Stessa logica per i canali artificiali.
LARGHEZZA_FERROVIA_M = {
    'rail': 12.0, 'light_rail': 8.0, 'narrow_gauge': 8.0, 'tram': 6.0,
    'subway': 6.0, 'preserved': 8.0, 'disused': 6.0, 'abandoned': 4.0,
}
IGNORA_FERROVIA = {'abandoned', 'razed', 'dismantled', 'proposed', 'construction'}
LARGHEZZA_ACQUA_M = {'canal': 8.0, 'ditch': 3.0, 'drain': 3.0, 'stream': 4.0, 'river': 12.0}

RIS_M = 1.0                      # 1 m/px: le carraie sono strette
D_AUTOSTRADA_IDONEA_M = 300.0    # art. 20 c.8 lett. c-ter D.Lgs 199/2021


def _cache_path(bbox):
    import hashlib
    import os
    try:
        from . import config as C
        base = str(C.CACHE_DIR)
    except Exception:
        base = os.path.join(os.path.expanduser('~'), '.land-scout-cache')
    d = os.path.join(base, 'strade')
    os.makedirs(d, exist_ok=True)
    h = hashlib.md5(('v2_%.5f_%.5f_%.5f_%.5f' % tuple(bbox)).encode()).hexdigest()[:16]
    return os.path.join(d, h + '.json')


def scarica(bbox, timeout=120, includi_sentieri=False, cache=True, tentativi=3):
    """Viabilita' OSM nel bbox (lat_min, lon_min, lat_max, lon_max).

    Con cache su disco e ritentativo: Overpass risponde 429 con facilita' quando
    si analizzano piu' blocchi di fila, e un blocco senza strade non e' un blocco
    senza strade — e' un blocco non verificato. Se la rete non risponde si
    solleva l'errore invece di restituire una lista vuota.
    """
    import os
    import time
    p = _cache_path(bbox)
    if cache and os.path.exists(p):
        return json.load(open(p, encoding='utf-8'))

    bb = f'{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}'
    q = (f'[out:json][timeout:120];('
         f'way["highway"]({bb});'
         f'way["railway"]({bb});'
         f');out geom;')
    d, errori = None, []
    for k in range(tentativi):
        for ep in OVERPASS:
            try:
                req = urllib.request.Request(
                    ep, data=urllib.parse.urlencode({'data': q}).encode(),
                    headers={'User-Agent': 'land-scout strade'})
                d = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
                break
            except Exception as e:
                errori.append(f'{ep.split("/")[2]}: {type(e).__name__}')
        if d is not None:
            break
        time.sleep(5 * (k + 1))
    if d is None:
        # meglio fermarsi che restituire zero strade: un blocco "senza strade"
        # non verificato e' peggio di un errore
        raise RuntimeError('Overpass non raggiungibile: ' + '; '.join(errori[-3:]))
    out = []
    for w in d.get('elements', []):
        g = w.get('geometry')
        if not g:
            continue
        tg = w.get('tags') or {}
        if tg.get('railway'):
            cls, tipo = tg['railway'], 'ferrovia'
            if cls in IGNORA_FERROVIA:
                continue
        else:
            cls, tipo = tg.get('highway'), 'strada'
            if not includi_sentieri and cls in IGNORA:
                continue
        out.append({'classe': cls, 'tipo': tipo, 'nome': tg.get('name'),
                    'geom': [(q2['lat'], q2['lon']) for q2 in g]})
    if cache:
        json.dump(out, open(p, 'w', encoding='utf-8'))
    return out


def _proj(polys):
    lats = [q[0] for p in polys for q in p]
    la0 = (min(lats) + max(lats)) / 2
    k = 111320 * math.cos(math.radians(la0))
    return (lambda pts: [(q[1] * k, q[0] * 110540) for q in pts]), la0


def maschera(particelle, strade, ris=RIS_M, margine=30.0):
    """Maschera booleana della sede stradale, allineata alle particelle.

    Restituisce (mask, geo) con geo = (x0, y0, W, H), nella stessa proiezione e
    risoluzione usate da `installabile`, cosi' le due maschere si combinano.
    """
    polys = [p['poly'] for p in particelle]
    M, _ = _proj(polys)
    mp = [M(p) for p in polys]
    xs = [x for p in mp for x, y in p]
    ys = [y for p in mp for x, y in p]
    x0, y0 = min(xs) - margine, min(ys) - margine
    W = int((max(xs) - x0 + margine) / ris) + 1
    H = int((max(ys) - y0 + margine) / ris) + 1
    img = Image.new('1', (W, H), 0)
    dr = ImageDraw.Draw(img)
    for s in strade:
        g = M(s['geom'])
        lw = (LARGHEZZA_FERROVIA_M.get(s.get('classe'), 12.0)
              if s.get('tipo') == 'ferrovia'
              else LARGHEZZA_M.get(s.get('classe'), 4.0))
        pts = [((x - x0) / ris, H - 1 - (y - y0) / ris) for x, y in g]
        if len(pts) > 1:
            dr.line(pts, fill=1, width=max(1, int(round(lw / ris))))
    return np.array(img, dtype=bool), (x0, y0, W, H)


def occupazione(particelle, strade, ris=RIS_M):
    """Quanto di ogni particella e' sede stradale, e quanto ne resta.

    Nessun verdetto di esclusione: una particella al 12% di strada resta
    utilizzabile per il resto. Serve a non contare ettari che non esistono e a
    far emergere i casi in cui la strada TAGLIA il fondo.
    """
    mask, (x0, y0, W, H) = maschera(particelle, strade, ris)
    M, _ = _proj([p['poly'] for p in particelle])
    px_ha = ris * ris / 10000.0
    out = []
    for p in particelle:
        m = M(p['poly'])
        one = Image.new('1', (W, H), 0)
        ImageDraw.Draw(one).polygon([((x - x0) / ris, H - 1 - (y - y0) / ris) for x, y in m],
                                    fill=1)
        a = np.array(one, dtype=bool)
        tot = a.sum()
        s = (a & mask).sum()
        out.append({'fg': p['fg'], 'pla': p['pla'],
                    'strada_pct': round(100 * s / tot, 1) if tot else 0.0,
                    'ha_strada': round(s * px_ha, 3)})
    return {'particelle': sorted(out, key=lambda q: -q['strada_pct']),
            'ha_sede_totale': round(sum(q['ha_strada'] for q in out), 2),
            'n_con_strada': sum(1 for q in out if q['strada_pct'] >= 5)}


def vicino_autostrada(particelle, strade, d_m=D_AUTOSTRADA_IDONEA_M):
    """Le aree entro 300 m dalla rete AUTOSTRADALE sono aree idonee per legge.

    art. 20 c.8 lett. c-ter D.Lgs 199/2021: iter accelerato. E' un BONUS, non un
    vincolo — ma vale per le autostrade, non per una statale a scorrimento
    veloce, che e' l'errore facile da fare guardando una foto aerea.
    """
    auto = [s for s in strade if s.get('classe') in ('motorway', 'motorway_link')]
    if not auto:
        return {'idonee': [], 'autostrade_trovate': 0,
                'nota': 'nessuna autostrada nel raggio scaricato: art. 20 c.8 c-ter non applicabile'}
    M, _ = _proj([p['poly'] for p in particelle] + [s['geom'] for s in auto])
    pts_auto = [q for s in auto for q in M(s['geom'])]
    idonee = []
    for p in particelle:
        m = M(p['poly'])
        d = min(math.dist(a, b) for a in m for b in pts_auto)
        if d <= d_m:
            idonee.append({'fg': p['fg'], 'pla': p['pla'], 'd_autostrada_m': round(d)})
    return {'idonee': idonee, 'autostrade_trovate': len(auto),
            'nota': 'art. 20 c.8 lett. c-ter D.Lgs 199/2021: iter accelerato entro 300 m'}


def print_occupazione(r, top=10):
    print(f"\n=== VIABILITA' ({r['ha_sede_totale']} ha di sede stradale nel blocco) ===")
    n = 0
    for q in r['particelle']:
        if q['strada_pct'] < 1 or n >= top:
            break
        print(f"   Fg{q['fg']}/{q['pla']:<7s} {q['strada_pct']:5.1f}% di sede stradale "
              f"({q['ha_strada']:.2f} ha)")
        n += 1
    if not n:
        print('   nessuna particella con sede stradale rilevabile')
    print(f"   ~ La sede non e' installabile; le FASCE DI RISPETTO riguardano le costruzioni "
          f"(DM 1404/1968, art. 26 Reg. CdS) e sono da verificare con l'ente gestore, "
          f"non sono un blocco all'idoneita'.")

FASCIA_PERTINENZA_M = 20.0     # scarpata, banchina, fosso di guardia
QUOTA_FASCIA_ESCLUSIONE = 70.0  # oltre, la particella E la fascia stradale


def quota_in_fascia(particelle, strade, d_m=FASCIA_PERTINENZA_M, ris=2.0):
    """Quanta parte di ogni particella sta DENTRO il corridoio stradale.

    Serve a cogliere quello che `occupazione()` non vede: una striscia che corre
    PARALLELA alla strada puo' avere poca sede stradale dentro il perimetro e
    essere comunque, tutta intera, scarpata e banchina. Su Morcone Fg83/14
    risultava all'11,9% di sede — e sta al 100% dentro il corridoio: non e' un
    campo lungo una strada, e' la strada.

    Un fondo normale confina con una strada su un lato: sta sotto il 30-40%.
    Oltre il 70% non c'e' piu' campo.
    """
    mask, (x0, y0, W, H) = maschera(particelle, strade, ris=ris, margine=d_m + 40)
    m = mask
    for _ in range(max(1, int(round(d_m / ris)))):
        c = np.zeros_like(m); c[1:, :] = m[:-1, :]
        u = np.zeros_like(m); u[:-1, :] = m[1:, :]
        l = np.zeros_like(m); l[:, 1:] = m[:, :-1]
        r = np.zeros_like(m); r[:, :-1] = m[:, 1:]
        m = m | c | u | l | r
    M, _ = _proj([p['poly'] for p in particelle])
    out = {}
    for p in particelle:
        g = M(p['poly'])
        one = Image.new('1', (W, H), 0)
        ImageDraw.Draw(one).polygon([((x - x0) / ris, H - 1 - (y - y0) / ris) for x, y in g],
                                    fill=1)
        a = np.array(one, dtype=bool)
        tot = a.sum()
        out[f"{p['fg']}_{p['pla']}"] = round(100 * (a & m).sum() / tot, 1) if tot else 0.0
    return out
