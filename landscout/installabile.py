"""land-scout installabile — quanti ettari del blocco reggono davvero i moduli.

Il problema che risolve, trovato a Morcone il 20/07: Fg82/117 risultava
"2,35 ha utili" e per superficie era la seconda particella del blocco. Al
satellite e' un **nastro di 1,5 km lungo un torrente**, largo una ventina di
metri. Nessuno ci installa niente. La superficie e' giusta; la forma la rende
inservibile, e nessun controllo su vincoli o fabbricati puo' accorgersene.

La tentazione e' scartare le particelle strette. Sarebbe sbagliato: **una
striscia stretta CIRCONDATA da altre particelle del blocco e' perfettamente
utilizzabile**, perche' le file di moduli la attraversano senza sapere che li'
sotto cambia l'intestatario. Il catasto non e' un vincolo fisico.

Quindi non si misura la forma della singola particella, ma quella del BLOCCO:
si fonde l'insieme in un'unica maschera e la si **erode** del franco di rispetto
(default 12,5 m: meta' della distanza tipica fra file, piu' l'arretramento dai
confini). Cio' che sopravvive all'erosione e' cio' che ospita davvero i moduli.
Le strisce interne sopravvivono perche' i vicini le sostengono; le code e i
nastri protrudenti spariscono, che e' esattamente il comportamento voluto.

Uso:
    from landscout import installabile
    r = installabile.analizza(blk['particelle'], franco_m=12.5)
    print(installabile.print_analisi(r))
    installabile.png(r, 'forma_blocco.png')      # verifica visiva
"""
import math

import numpy as np
from PIL import Image, ImageDraw

FRANCO_M = 12.5      # meta' interfila tipica agriPV + arretramento dai confini
RIS_M = 2.0          # risoluzione della maschera in metri/pixel
LARGH_MIN_M = 25.0   # sotto, una particella ISOLATA e' un nastro (solo diagnostica)


def _proj(polys):
    """Proiezione piana con UNA origine per tutto l'insieme (vedi blocco._metrico)."""
    lats = [q[0] for p in polys for q in p]
    la0 = (min(lats) + max(lats)) / 2
    k = 111320 * math.cos(math.radians(la0))
    return [[(q[1] * k, q[0] * 110540) for q in p] for p in polys]


def _area(m):
    n = len(m)
    return abs(sum(m[i][0] * m[(i + 1) % n][1] - m[(i + 1) % n][0] * m[i][1]
                   for i in range(n))) / 2


def _maschera(mp, ris=RIS_M, margine=40.0):
    xs = [x for p in mp for x, y in p]
    ys = [y for p in mp for x, y in p]
    x0, y0 = min(xs) - margine, min(ys) - margine
    W = int((max(xs) - x0 + margine) / ris) + 1
    H = int((max(ys) - y0 + margine) / ris) + 1
    img = Image.new('1', (W, H), 0)
    dr = ImageDraw.Draw(img)
    for p in mp:
        dr.polygon([((x - x0) / ris, H - 1 - (y - y0) / ris) for x, y in p], fill=1)
    return np.array(img, dtype=bool), (x0, y0, W, H)


def _erodi(mask, passi):
    """Erosione binaria iterativa 4-connessa (niente scipy in questo ambiente).

    `passi` iterazioni ≈ `passi * ris` metri di franco. Bordo trattato come
    esterno: una particella sul bordo della maschera arretra, come deve.
    """
    m = mask
    for _ in range(passi):
        c = np.zeros_like(m)
        c[1:, :] = m[:-1, :]
        u = np.zeros_like(m)
        u[:-1, :] = m[1:, :]
        l = np.zeros_like(m)
        l[:, 1:] = m[:, :-1]
        r = np.zeros_like(m)
        r[:, :-1] = m[:, 1:]
        m = m & c & u & l & r
        if not m.any():
            break
    return m


def analizza(particelle, franco_m=FRANCO_M, ris=RIS_M, strade=None):
    """Superficie NETTA (catastale meno vincoli) vs superficie INSTALLABILE.

    particelle: [{'fg','pla','netti','poly'[,'ancora']}] — il blocco intero.
    strade: elenco da `strade.scarica()`. La sede stradale viene tolta dalla
    maschera PRIMA dell'erosione, ed e' questo il punto: una carraia che
    attraversa un fondo non toglie solo i suoi 3 metri, **spezza il campo in
    due** e fa arretrare i moduli su entrambi i lati. Contarla dopo, come
    semplice sottrazione di ettari, ne mancherebbe l'effetto principale.
    """
    polys = [p['poly'] for p in particelle]
    mp = _proj(polys)
    mask, geo = _maschera(mp, ris)
    if strade:
        from . import strade as ST
        road, _ = ST.maschera(particelle, strade, ris=ris, margine=40.0)
        if road.shape == mask.shape:
            mask = mask & ~road
    passi = max(1, int(round(franco_m / ris)))
    ero = _erodi(mask, passi)

    px_ha = (ris * ris) / 10000.0
    ha_unione = mask.sum() * px_ha
    ha_inst = ero.sum() * px_ha

    # quota installabile per particella: si rasterizza la singola e si interseca
    x0, y0, W, H = geo
    per_part = []
    for p, m in zip(particelle, mp):
        one = Image.new('1', (W, H), 0)
        ImageDraw.Draw(one).polygon([((x - x0) / ris, H - 1 - (y - y0) / ris) for x, y in m], fill=1)
        a = np.array(one, dtype=bool)
        tot = a.sum()
        inst = (a & ero).sum()
        larg = _area(m) / max(math.dist(u, v) for u in m for v in m) if len(m) > 1 else 0
        per_part.append({
            'fg': p['fg'], 'pla': p['pla'], 'ancora': p.get('ancora'),
            'ha_netti': p.get('netti'),
            'ha_installabile': round(inst * px_ha, 3),
            'quota_installabile': round(inst / tot, 3) if tot else 0.0,
            'larghezza_m': round(larg, 1),
        })

    persi = [q for q in per_part if q['quota_installabile'] < 0.25]

    # La geometria fornisce il FATTORE DI FORMA; gli ETTARI restano quelli
    # catastali al netto dei vincoli. Le due misure divergono sempre un po'
    # (superficie catastale dichiarata vs superficie grafica del poligono) e
    # ancorare il risultato al dato catastale evita di annunciare piu' ettari
    # installabili di quanti ne risultino in visura.
    ha_netti = round(sum(p.get('netti') or 0 for p in particelle), 2)
    resa = (ha_inst / ha_unione) if ha_unione else 0.0
    return {
        'ha_netti_dichiarati': ha_netti,
        'ha_unione_geometrica': round(ha_unione, 2),
        'ha_installabile_geometrico': round(ha_inst, 2),
        'ha_installabile': round(ha_netti * resa, 2),
        'resa_forma': round(resa, 3),
        'franco_m': franco_m, 'risoluzione_m': ris,
        'particelle': sorted(per_part, key=lambda q: q['quota_installabile']),
        'quasi_inutili': persi,
        'nota': ('Superficie che sopravvive all\'erosione del blocco fuso: le strisce '
                 'INTERNE restano (i vicini le sostengono), le code e i nastri protrudenti '
                 'no. Una particella stretta non e\' un difetto se sta dentro il blocco.'),
    }


def print_analisi(r, top=12):
    print(f"\n=== SUPERFICIE INSTALLABILE (franco {r['franco_m']} m) ===")
    print(f"  netti dichiarati : {r['ha_netti_dichiarati']} ha")
    print(f"  unione geometrica: {r['ha_unione_geometrica']} ha")
    print(f"  INSTALLABILE     : {r['ha_installabile']} ha  "
          f"(resa di forma {100*r['resa_forma']:.0f}%)")
    if r['quasi_inutili']:
        print(f"  particelle che spariscono quasi del tutto ({len(r['quasi_inutili'])}):")
        for q in r['quasi_inutili'][:top]:
            chi = 'FAM' if q['ancora'] else 'acq'
            print(f"    Fg{q['fg']}/{q['pla']:<7s} {q['ha_netti']:5.2f} ha netti -> "
                  f"{q['ha_installabile']:5.2f} installabili ({100*q['quota_installabile']:3.0f}%) "
                  f"largh ~{q['larghezza_m']:.0f} m  [{chi}]")
    print(f"  ~ {r['nota']}")


def png(particelle, out, franco_m=FRANCO_M, ris=RIS_M):
    """Immagine di verifica: grigio = blocco, verde = installabile."""
    mp = _proj([p['poly'] for p in particelle])
    mask, geo = _maschera(mp, ris)
    ero = _erodi(mask, max(1, int(round(franco_m / ris))))
    rgb = np.zeros(mask.shape + (3,), dtype=np.uint8)
    rgb[mask] = (90, 90, 90)
    rgb[ero] = (60, 200, 90)
    Image.fromarray(rgb).save(out)
    return out
