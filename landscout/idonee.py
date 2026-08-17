# -*- coding: utf-8 -*-
"""land-scout idonee — dove l'iter e' AGEVOLATO, non solo dove e' bloccato.

Tutto il resto del tool risponde alla domanda difensiva: *cosa mi blocca?*
Vincoli, habitat, fabbricati, bosco, crinali, PAI. Manca la domanda opposta, che
e' quella che fa scegliere un sito a un developer: **dove si va piu' in fretta?**
Il D.Lgs 199/2021 art. 20 c. 8 elenca aree in cui l'impianto e' *idoneo per
legge* — l'autorizzazione unica ha termini ridotti e la valutazione dei vincoli
paesaggistici e' semplificata. Con la L. 4/2026 i tempi dell'AU in area idonea
scendono di un terzo, e il Consiglio di Stato (sent. 6151/2026 del 30/07/2026)
ha rimesso in vigore il DM 21/06/2024 nella sua versione originaria: la
categoria e' viva e conviene saperla riconoscere.

CHE COSA CONTROLLA (criteri geometrici, gli unici automatizzabili)
------------------------------------------------------------------
- **lett. c-ter, 500 m**: aree agricole racchiuse in un perimetro i cui punti
  distano non piu' di 500 m da zone a destinazione industriale, artigianale o
  commerciale;
- **lett. c-ter, 300 m**: aree adiacenti alla rete autostradale entro 300 m
  (delegato a `strade.vicino_autostrada`, che gia' distingue l'autostrada da una
  statale a scorrimento veloce — l'errore facile guardando una foto aerea);
- **lett. c**: cave e miniere cessate, abbandonate o in degrado ambientale;
- **discariche chiuse o ripristinate** (art. 20 c. 1-bis).

CHE COSA NON PUO' FARE, ed e' importante quanto il resto
--------------------------------------------------------
1. **OSM e' un INNESCO, non la perimetrazione ufficiale.** Un `landuse=industrial`
   disegnato da un mappatore non e' una zona D del PRG, e una cava dismessa puo'
   non essere mappata affatto. Cio' che esce di qui e' *"candidata, verifica"*,
   mai *"idonea"*. La perimetrazione buona sta nella piattaforma **GSE aree
   idonee** (`areeidonee.gse.it`, dal 22/05/2025, aggiornamento trimestrale,
   consultabile via webGIS) e nella legge regionale.
2. **Non dichiara MAI una NON idoneita'.** Le aree non idonee dipendono dalla
   norma regionale, che qui non c'e'; e dopo Corte cost. 184/2025 l'inidoneita'
   non equivale comunque a un divieto assoluto. Un campo `area_non_idonea`
   riempito a caso sarebbe la solita assenza di dato travestita da verdetto.
3. **Se Overpass non risponde, l'esito e' `None`** — non idonea *e nemmeno* non
   idonea: non verificata.

Uso:
    from landscout import idonee
    inn = idonee.innesco(particelle)
    R = idonee.valuta(particelle, inn, strade=S)
    print(idonee.print_report(R))
"""
import json
import math
import urllib.parse
import urllib.request

OVERPASS = ['https://overpass-api.de/api/interpreter',
            'https://overpass.kumi.systems/api/interpreter',
            'https://overpass.private.coffee/api/interpreter']
UA = {'User-Agent': 'land-scout idonee'}

D_INDUSTRIALE_M = 500.0      # art. 20 c.8 lett. c-ter
D_AUTOSTRADA_M = 300.0       # art. 20 c.8 lett. c-ter (via strade.vicino_autostrada)

# Innesco OSM: cio' che, se confermato, fa scattare una categoria di idoneita'.
TAG_INNESCO = {
    'industriale': [('landuse', 'industrial'), ('landuse', 'commercial'),
                    ('landuse', 'retail')],
    'cava': [('landuse', 'quarry')],
    'discarica': [('landuse', 'landfill')],
}
CRITERIO = {
    'industriale': ('art. 20 c.8 lett. c-ter D.Lgs 199/2021: entro 500 m da zona '
                    'industriale/artigianale/commerciale'),
    'cava': ('art. 20 c.8 lett. c D.Lgs 199/2021: cava o miniera cessata, abbandonata '
             'o in degrado ambientale'),
    'discarica': ('art. 20 c. 1-bis D.Lgs 199/2021: discarica chiusa o ripristinata'),
    'autostrada': ('art. 20 c.8 lett. c-ter D.Lgs 199/2021: entro 300 m dalla rete '
                   'autostradale'),
}


class InnescoNonDisponibile(RuntimeError):
    """Overpass muto: l'idoneita' resta NON verificata, mai negata."""


def _overpass(q, timeout=120, tentativi=2):
    errori = []
    for _ in range(tentativi):
        for ep in OVERPASS:
            try:
                req = urllib.request.Request(
                    ep, data=urllib.parse.urlencode({'data': q}).encode(), headers=UA)
                return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
            except Exception as e:
                errori.append(f'{ep.split("/")[2]}: {type(e).__name__}')
    raise InnescoNonDisponibile('Overpass non raggiunto (' + ', '.join(errori[:3]) + ')')


def _bbox(particelle, margine_gradi=0.006):
    la = [q[0] for p in particelle for q in p['poly']]
    lo = [q[1] for p in particelle for q in p['poly']]
    return (min(la) - margine_gradi, min(lo) - margine_gradi,
            max(la) + margine_gradi, max(lo) + margine_gradi)


def _proj(la0):
    mlat = 111132.0
    mlon = 111320.0 * math.cos(math.radians(la0))
    return lambda la, lo: (lo * mlon, la * mlat)


def _dentro(punto, anello):
    """Ray casting: il centroide sta dentro il poligono d'innesco?"""
    x, y = punto
    dentro = False
    n = len(anello)
    for i in range(n):
        x1, y1 = anello[i]
        x2, y2 = anello[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xx = x1 + (y - y1) * (x2 - x1) / ((y2 - y1) or 1e-12)
            if x < xx:
                dentro = not dentro
    return dentro


def innesco(particelle, timeout=120, margine_gradi=0.006):
    """Geometrie OSM che possono far scattare un'idoneita', nel bbox delle particelle.

    Il margine e' generoso di proposito: la zona industriale che rende idonea la
    particella puo' stare fuori dal blocco, ed e' il caso normale.
    """
    if not particelle:
        raise ValueError('nessuna particella')
    bb = _bbox(particelle, margine_gradi)
    parti = []
    for tipi in TAG_INNESCO.values():
        for k, v in tipi:
            parti.append(f'way["{k}"="{v}"]({bb[0]},{bb[1]},{bb[2]},{bb[3]});')
            parti.append(f'relation["{k}"="{v}"]({bb[0]},{bb[1]},{bb[2]},{bb[3]});')
    d = _overpass(f'[out:json][timeout:120];({"".join(parti)});out geom tags;', timeout)

    per_tipo = {k: [] for k in TAG_INNESCO}
    for e in d.get('elements', []):
        g = e.get('geometry') or []
        if len(g) < 3:
            continue
        tg = e.get('tags') or {}
        for tipo, coppie in TAG_INNESCO.items():
            if any(tg.get(k) == v for k, v in coppie):
                per_tipo[tipo].append({
                    'nome': tg.get('name') or '(senza nome)',
                    'anello': [(x['lat'], x['lon']) for x in g],
                    'dismesso': bool(tg.get('disused') or tg.get('abandoned') or
                                     tg.get('landuse', '').startswith('disused')),
                })
                break
    return {'per_tipo': per_tipo, 'bbox': bb,
            'trovati': {k: len(v) for k, v in per_tipo.items()},
            'nota': ('geometrie OSM come innesco: la perimetrazione ufficiale sta nella '
                     'piattaforma GSE aree idonee e nella legge regionale')}


def valuta(particelle, inn, strade=None, d_industriale=D_INDUSTRIALE_M):
    """Per ogni particella: quali criteri di idoneita' potrebbe soddisfare.

    `strade` e' l'uscita di `strade.scarica()`: se c'e', il criterio dei 300 m
    dall'autostrada viene delegato a `strade.vicino_autostrada()` invece di
    essere riscritto qui. Due implementazioni della stessa regola darebbero due
    risposte diverse, ed e' il modo piu' semplice per non fidarsi piu' di nessuna.
    """
    la0 = sum(q[0] for p in particelle for q in p['poly']) / \
        sum(len(p['poly']) for p in particelle)
    M = _proj(la0)
    inn_m = {tipo: [(g['nome'], [M(a, b) for a, b in g['anello']], g['dismesso'])
                    for g in gs]
             for tipo, gs in (inn.get('per_tipo') or {}).items()}

    auto = {}
    nota_auto = None
    if strade is not None:
        try:
            from . import strade as ST
            r = ST.vicino_autostrada(particelle, strade)
            auto = {f"{x['fg']}_{x['pla']}": x['d_autostrada_m'] for x in r['idonee']}
            nota_auto = r['nota']
        except Exception as e:
            nota_auto = f'autostrada non verificata ({type(e).__name__})'

    out = {}
    for p in particelle:
        k = f"{p['fg']}_{p['pla']}"
        vert = [M(a, b) for a, b in p['poly']]
        cx = sum(v[0] for v in vert) / len(vert)
        cy = sum(v[1] for v in vert) / len(vert)
        criteri, dist = [], {}
        for tipo, gs in inn_m.items():
            if not gs:
                continue
            # la distanza si misura sui VERTICI: sovrastima (il punto piu' vicino
            # puo' stare su un lato), quindi qualche idoneita' sfugge invece di
            # essere inventata. In questa direzione l'errore e' accettabile.
            d = min(min(math.dist(v, w) for v in vert for w in an) for _, an, _ in gs)
            if any(_dentro((cx, cy), an) for _, an, _ in gs):
                d = 0.0
            dist[tipo] = round(d)
            if tipo == 'industriale' and d <= d_industriale:
                criteri.append(('industriale', CRITERIO['industriale'], round(d)))
            elif tipo in ('cava', 'discarica') and d == 0.0:
                criteri.append((tipo, CRITERIO[tipo], 0))
        if k in auto:
            criteri.append(('autostrada', CRITERIO['autostrada'], auto[k]))
        out[k] = {'candidata': bool(criteri),
                  'criteri': [{'tipo': t, 'norma': n, 'd_m': d} for t, n, d in criteri],
                  'distanze_m': dist}
    return {'particelle': out,
            'n_candidate': sum(1 for v in out.values() if v['candidata']),
            'n_totale': len(out),
            'innesco': inn.get('trovati'),
            'nota_autostrada': nota_auto,
            'nota': ('CANDIDATE, non idonee: la perimetrazione ufficiale e nella '
                     'piattaforma GSE (areeidonee.gse.it) e nella legge regionale. '
                     'Nessuna NON idoneita e dichiarata qui: dipende dalla norma '
                     'regionale e, dopo Corte cost. 184/2025, non equivale a un divieto.')}


def applica(A, R):
    """Segna le candidate sulle ammesse. Non tocca gli ettari: e' un bonus di ITER.

    Il campo `area_idonea` e' quello che `engine.score_parcel` gia' legge (+10 al
    punteggio): finora non lo riempiva nessuno, e infatti l'unico criterio
    implementato — i 300 m dall'autostrada — restava una nota che non entrava in
    nessuna decisione.
    """
    n = 0
    for a in A['ammesse']:
        v = (R.get('particelle') or {}).get(f"{a['fg']}_{a['pla']}")
        if not v:
            continue
        if v['candidata']:
            a['area_idonea'] = True
            a['idonea_criteri'] = [c['tipo'] for c in v['criteri']]
            n += 1
    return dict(A, idonee={'candidate': n, 'valutate': len(R.get('particelle') or {}),
                           'nota': R['nota']})


def print_report(R, top=12):
    L = [f"AREE IDONEE (candidate): {R['n_candidate']}/{R['n_totale']} particelle",
         f"  innesco OSM: " + ', '.join(f'{k} {v}' for k, v in (R['innesco'] or {}).items())]
    mostrate = 0
    for k, v in R['particelle'].items():
        if not v['candidata'] or mostrate >= top:
            continue
        mostrate += 1
        for c in v['criteri']:
            L.append(f"  {k:<12s} {c['tipo']:<12s} {c['d_m']:>5d} m — {c['norma']}")
    if R.get('nota_autostrada'):
        L.append('  ' + R['nota_autostrada'])
    L.append('  ' + R['nota'])
    return '\n'.join(L)
