"""land-scout crinali — la fascia di rispetto dei crinali (PTCP Benevento art. 32).

Perche' esiste questo modulo: il **27/07/2026** e' emerso che la Provincia di
Benevento ha impugnato al TAR (delibera 106 del 30/04/2026) il PAUR n. 66 del
03/03/2026 con cui la Regione aveva autorizzato il fotovoltaico RWE da 19,99 MWp
a Pontelandolfo. Il motivo del ricorso e' il contrasto con il PTCP provinciale
sulle **fasce di rispetto dei crinali spartiacque**. Nessun modulo del tool
guardava i crinali: un blocco poteva uscire "pulito" e trovarsi dentro una fascia
che un ente locale usa per fare causa a progetti gia' autorizzati.

**La norma** — PTCP BN, Norme Tecniche di Attuazione, art. 32 "Prescrizioni per
le aree di crinale":

- ampiezza: *"aree di crinale (**fascia di 300 metri ai lati della linea di
  crinale**)"* — cioe' un corridoio largo 600 m centrato sulla linea;
- due categorie, cartografate nella **tavola A 2.2e "Bacini visivi"**:
  **crinali spartiacque principali** (spartiacque di connotazione fisiografica e
  paesistica generale) e **crinali minori** (dorsali di connotazione locale);
- i crinali minori vincolano **solo dove il Comune lo ha deciso** in sede di
  adeguamento del PUC al PTCP (art. 32 c. 2.1): non sono automatici;
- la prescrizione che morde un impianto: *"vanno evitati **sbancamenti** del
  terreno che alterino la percezione visiva delle linee di crinale; in tale
  ambito va inoltre evitata l'edificazione di nuove infrastrutture stradali o
  **reti tecnologiche in superficie (elettrodotti, linee telefoniche aeree)**"*.

Due appigli difensivi, da conoscere prima di trattare: (1) un cavidotto
**interrato** non e' una rete "in superficie"; (2) formalmente l'art. 32 detta
**indirizzi alla pianificazione comunale**, non divieti diretti al singolo
progetto — ed e' esattamente il punto su cui si litiga al TAR.

⚠️ **Cosa NON e' questo modulo.** Le linee di crinale ufficiali stanno nella
tavola A 2.2e del PTCP, non in un DEM. Qui i crinali si **derivano dal modello
del terreno**: il risultato dice DOVE guardare e quanto e' probabile il problema,
non se la particella e' vincolata. Stessa filosofia di `prossimita.beni_tutelati`.
Nel dubbio il modulo sbaglia per eccesso di segnalazioni, mai per difetto.

Uso:
    from landscout import crinali
    r = crinali.fascia_crinali(particelle)          # buffer 300 m, DEM srtm30m
    crinali.stampa(r)
"""
import json
import math
import time
import urllib.parse
import urllib.request

UA = {'User-Agent': 'land-scout crinali'}

BUFFER_CRINALE_M = 300.0     # PTCP BN art. 32: fascia ai lati della linea di crinale
PASSO_GRIGLIA_M = 90.0       # passo di campionamento del DEM
MARGINE_M = 1200.0           # quanto allargare il bbox: un crinale fuori blocco vincola lo stesso
PROMINENZA_MIN_M = 5.0       # dislivello minimo per non scambiare rumore del DEM per crinale
DIREZIONI_MIN = 2            # su 4: quante direzioni devono avere la cella come massimo locale
CELLE_MIN_DORSALE = 3        # una "linea di crinale" e' una linea: 1-2 celle sono rumore
ESTENSIONE_MIN_M = 300.0     # idem: sotto questa estensione non e' una dorsale, e' un dosso
LUNGH_PRINCIPALE_M = 1500.0  # estensione oltre la quale una dorsale e' candidata "principale"

# Combinazioni usate per dichiarare la sensibilita' del risultato alle soglie.
# (direzioni_min, prominenza_m, celle_min, estensione_min_m, etichetta)
_SENSIBILITA = [
    (2, 2.0, 1, 0.0, 'nessun filtro di linearita (limite superiore)'),
    (2, 2.0, 3, 300.0, 'permissiva'),
    (2, 5.0, 3, 300.0, 'DEFAULT'),
    (2, 10.0, 3, 300.0, 'prominenza alta'),
    (3, 2.0, 3, 300.0, 'creste nette'),
    (2, 5.0, 5, 600.0, 'solo dorsali lunghe'),
    (3, 5.0, 3, 300.0, 'stretta (limite inferiore)'),
]


def _proj(lat0):
    """Proiezione metrica locale (x = est, y = nord), in metri."""
    k = 111320 * math.cos(math.radians(lat0))
    return (lambda la, lo: (lo * k, la * 110540))


def _bbox(particelle, margine_gradi):
    la = [q[0] for p in particelle for q in p['poly']]
    lo = [q[1] for p in particelle for q in p['poly']]
    return (min(la) - margine_gradi, min(lo) - margine_gradi,
            max(la) + margine_gradi, max(lo) + margine_gradi)


def _griglia(bb, passo_m):
    """Griglia regolare di (lat, lon) sul bbox, con passo ~costante in metri."""
    la0 = (bb[0] + bb[2]) / 2
    dlat = passo_m / 110540
    dlon = passo_m / (111320 * math.cos(math.radians(la0)))
    lats = []
    x = bb[0]
    while x <= bb[2]:
        lats.append(x)
        x += dlat
    lons = []
    y = bb[1]
    while y <= bb[3]:
        lons.append(y)
        y += dlon
    return lats, lons


def _quote(punti, dataset, timeout, punti_max=100, pausa=1.1):
    """Interroga opentopodata. Ritorna una lista di quote, None dove non risponde."""
    out = [None] * len(punti)
    falliti = 0
    for i in range(0, len(punti), punti_max):
        blocco = punti[i:i + punti_max]
        locs = '|'.join(f'{a},{b}' for a, b in blocco)
        url = (f'https://api.opentopodata.org/v1/{dataset}'
               f'?locations={urllib.parse.quote(locs, safe=",|")}')
        try:
            r = json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=timeout).read())
            for j, x in enumerate(r.get('results', [])):
                out[i + j] = x.get('elevation')
        except Exception:
            falliti += 1
        time.sleep(pausa)
    return out, falliti


def _celle_crinale(z, direzioni_min=DIREZIONI_MIN, prominenza=PROMINENZA_MIN_M):
    """Celle di crinale su una griglia di quote.

    Una cella e' di crinale se e' massimo locale lungo almeno `direzioni_min`
    delle 4 direzioni (E-O, N-S, NE-SO, NO-SE), con un dislivello minimo. Su una
    dorsale lineare la cella e' massimo nelle direzioni trasversali ma non lungo
    la dorsale: per questo la soglia e' 2 su 4 e non 4 su 4 (che darebbe le sole
    vette). `z` e' una matrice con None dove il DEM non ha risposto.
    """
    nr, nc = len(z), len(z[0]) if z else 0
    dirs = ((0, 1), (1, 0), (1, 1), (1, -1))
    out = set()
    for i in range(1, nr - 1):
        for j in range(1, nc - 1):
            c = z[i][j]
            if c is None:
                continue
            n_cresta = 0
            for di, dj in dirs:
                a, b = z[i - di][j - dj], z[i + di][j + dj]
                if a is None or b is None:
                    continue
                if c >= a and c >= b and (c - min(a, b)) >= prominenza:
                    n_cresta += 1
            if n_cresta >= direzioni_min:
                out.add((i, j))
    return out


def _componenti(celle):
    """Raggruppa le celle di crinale in dorsali connesse (8-connettivita')."""
    resto, comps = set(celle), []
    while resto:
        seme = resto.pop()
        comp, coda = {seme}, [seme]
        while coda:
            i, j = coda.pop()
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    v = (i + di, j + dj)
                    if v in resto:
                        resto.discard(v)
                        comp.add(v)
                        coda.append(v)
        comps.append(comp)
    return comps


def _dorsali(z, lats, lons, M, direzioni_min, prominenza, celle_min, estensione_min_m):
    """Dorsali (componenti connesse di celle di crinale) che sono davvero LINEE.

    Il filtro di linearita' non e' cosmetico: senza, su un DEM a 90 m il rumore
    genera decine di massimi locali isolati e ogni particella finisce entro 300 m
    da "qualcosa". Il PTCP parla di *linee* di crinale, cartografate come tali.
    """
    celle = _celle_crinale(z, direzioni_min, prominenza)
    out = []
    for comp in _componenti(celle):
        pts = [M(lats[i], lons[j]) for i, j in comp]
        est = max(math.dist(a, b) for a in pts for b in pts) if len(pts) > 1 else 0.0
        if len(comp) < celle_min or est < estensione_min_m:
            continue
        qs = [z[i][j] for i, j in comp if z[i][j] is not None]
        out.append({'celle': comp, 'punti': pts, 'estensione_m': est,
                    'quota_media': sum(qs) / len(qs) if qs else None})
    return celle, out


def _pct_ha_entro(particelle, dorsali, M, buffer_m):
    ha_tot = ha_in = 0.0
    n_in = 0
    for p in particelle:
        ha = p.get('ha') or 0
        ha_tot += ha
        if not dorsali:
            continue
        vert = [M(q[0], q[1]) for q in p['poly']]
        d = min(math.dist(v, c) for dd in dorsali for v in vert for c in dd['punti'])
        if d <= buffer_m:
            ha_in += ha
            n_in += 1
    return (round(100 * ha_in / ha_tot, 1) if ha_tot else None), n_in


def fascia_crinali(particelle, buffer_m=BUFFER_CRINALE_M, dataset='srtm30m',
                   passo_m=PASSO_GRIGLIA_M, margine_m=MARGINE_M, timeout=90,
                   direzioni_min=DIREZIONI_MIN, prominenza=PROMINENZA_MIN_M,
                   celle_min=CELLE_MIN_DORSALE, estensione_min_m=ESTENSIONE_MIN_M,
                   lungh_principale_m=LUNGH_PRINCIPALE_M, griglia=None):
    """Particelle dentro la fascia di rispetto dei crinali (PTCP BN art. 32).

    Ritorna per ogni particella la distanza dalla dorsale piu' vicina, se sta
    dentro il buffer, e se la dorsale e' candidata "principale" (vincolo
    automatico) o "minore" (vincola solo se il PUC comunale l'ha recepita).

    Ritorna anche `sensibilita`: lo stesso conto sotto soglie diverse. **Va
    letto sempre**: su questo terreno il risultato passa da 0% a 100% a seconda
    delle soglie, quindi il numero singolo non e' una misura, e' un'indicazione.

    `griglia` accetta un DEM gia' scaricato ({'lats','lons','quote'}) per non
    ripetere migliaia di chiamate a ogni rilancio.
    """
    if not particelle:
        raise ValueError('nessuna particella')

    la0 = sum(q[0] for p in particelle for q in p['poly']) / \
        sum(len(p['poly']) for p in particelle)
    M = _proj(la0)

    if griglia:
        lats, lons, quote = griglia['lats'], griglia['lons'], griglia['quote']
        req_falliti = griglia.get('falliti', 0)
    else:
        bb = _bbox(particelle, margine_m / 110540)
        lats, lons = _griglia(bb, passo_m)
        quote, req_falliti = _quote([(a, b) for a in lats for b in lons], dataset, timeout)
    punti = [(a, b) for a in lats for b in lons]
    letti = sum(1 for q in quote if q is not None)
    if letti < 0.5 * len(punti):
        return {'verificato': False, 'particelle': {},
                'motivo': (f'DEM incompleto: {letti}/{len(punti)} quote lette '
                           f'({req_falliti} richieste fallite). '
                           'Assenza di dato NON vale come assenza di crinale.'),
                'nota': _NOTA}

    nc = len(lons)
    z = [[quote[i * nc + j] for j in range(nc)] for i in range(len(lats))]

    celle, dorsali = _dorsali(z, lats, lons, M, direzioni_min, prominenza,
                              celle_min, estensione_min_m)
    celle_strette = _celle_crinale(z, min(4, direzioni_min + 1), prominenza)

    sensibilita = []
    for dm, pr, cm, em, etichetta in _SENSIBILITA:
        _, ds = _dorsali(z, lats, lons, M, dm, pr, cm, em)
        pct, npart = _pct_ha_entro(particelle, ds, M, buffer_m)
        sensibilita.append({'etichetta': etichetta, 'direzioni_min': dm,
                            'prominenza_m': pr, 'celle_min': cm,
                            'estensione_min_m': em, 'dorsali': len(ds),
                            'pct_ha_entro': pct, 'n_particelle_entro': npart})

    if dorsali:
        quote_medie = sorted(d['quota_media'] for d in dorsali if d['quota_media'] is not None)
        mediana = quote_medie[len(quote_medie) // 2] if quote_medie else 0
        for d in dorsali:
            d['principale'] = bool(d['estensione_m'] >= lungh_principale_m and
                                   (d['quota_media'] or 0) >= mediana)

    out = {}
    for p in particelle:
        vert = [M(q[0], q[1]) for q in p['poly']]
        best = best_pri = None
        for d in dorsali:
            dd = min(math.dist(v, c) for v in vert for c in d['punti'])
            if best is None or dd < best[0]:
                best = (dd, d)
            if d['principale'] and (best_pri is None or dd < best_pri[0]):
                best_pri = (dd, d)
        k = f"{p['fg']}_{p['pla']}"
        out[k] = {
            'd_crinale_m': round(best[0]) if best else None,
            'entro_fascia': bool(best and best[0] <= buffer_m),
            'tipo_piu_vicino': ('principale' if best and best[1]['principale'] else 'minore')
            if best else None,
            'd_principale_m': round(best_pri[0]) if best_pri else None,
            'entro_fascia_principale': bool(best_pri and best_pri[0] <= buffer_m),
            'ha': p.get('ha'), 'ancora': p.get('ancora'),
        }

    entro = [v for v in out.values() if v['entro_fascia']]
    entro_pri = [v for v in out.values() if v['entro_fascia_principale']]
    ha_tot = sum(p.get('ha') or 0 for p in particelle)
    ha_entro = sum(v['ha'] or 0 for v in out.values() if v['entro_fascia'])
    ha_entro_pri = sum(v['ha'] or 0 for v in out.values() if v['entro_fascia_principale'])
    fam = [p for p in particelle if p.get('ancora')]
    ha_fam = sum(p.get('ha') or 0 for p in fam)
    ha_fam_entro = sum(out[f"{p['fg']}_{p['pla']}"]['ha'] or 0 for p in fam
                       if out[f"{p['fg']}_{p['pla']}"]['entro_fascia'])

    return {
        'verificato': True,
        'buffer_m': buffer_m,
        'dataset': dataset, 'passo_m': passo_m,
        'quote_lette': letti, 'quote_totali': len(punti),
        'dorsali': len(dorsali),
        'dorsali_principali': sum(1 for d in dorsali if d['principale']),
        'celle_crinale': len(celle),
        'celle_crinale_criterio_stretto': len(celle_strette),
        'particelle': out,
        'n_entro': len(entro), 'n_totale': len(out),
        'n_entro_principale': len(entro_pri),
        'ha_totali': round(ha_tot, 2),
        'ha_entro': round(ha_entro, 2),
        'ha_entro_principale': round(ha_entro_pri, 2),
        'pct_ha_entro': round(100 * ha_entro / ha_tot, 1) if ha_tot else None,
        'pct_ha_entro_principale': round(100 * ha_entro_pri / ha_tot, 1) if ha_tot else None,
        'ha_famiglia': round(ha_fam, 2),
        'ha_famiglia_entro': round(ha_fam_entro, 2),
        'pct_famiglia_entro': round(100 * ha_fam_entro / ha_fam, 1) if ha_fam else None,
        'sensibilita': sensibilita,
        'banda_pct': [min(s['pct_ha_entro'] for s in sensibilita if s['pct_ha_entro'] is not None),
                      max(s['pct_ha_entro'] for s in sensibilita if s['pct_ha_entro'] is not None)]
        if any(s['pct_ha_entro'] is not None for s in sensibilita) else None,
        'nota': _NOTA,
    }


_NOTA = (
    'Crinali derivati dal DEM, non dalla tavola A 2.2e "Bacini visivi" del PTCP BN: '
    'dice dove guardare, non cosa e\' vincolato. La distinzione principale/minore e\' '
    'una stima morfometrica (estensione + quota), non la classificazione del piano. '
    'I crinali minori vincolano solo dove il PUC comunale li ha recepiti (art. 32 c. 2.1). '
    'Verifica dovuta: tavola A 2.2e del PTCP e PUC di Morcone.'
)


def stampa(r):
    if not r.get('verificato'):
        print('CRINALI: NON VERIFICATO —', r.get('motivo'))
        print('  ' + r['nota'])
        return
    print(f"=== FASCIA DI RISPETTO CRINALI (PTCP BN art. 32, {r['buffer_m']:.0f} m per lato) ===")
    print(f"  DEM {r['dataset']} passo {r['passo_m']:.0f} m — "
          f"{r['quote_lette']}/{r['quote_totali']} quote lette")
    print(f"  dorsali rilevate: {r['dorsali']} (di cui candidate principali: "
          f"{r['dorsali_principali']})")
    print(f"  celle di crinale: {r['celle_crinale']} con criterio standard, "
          f"{r['celle_crinale_criterio_stretto']} con criterio stretto")
    print()
    print(f"  particelle nella fascia: {r['n_entro']}/{r['n_totale']}  "
          f"({r['ha_entro']} ha su {r['ha_totali']} = {r['pct_ha_entro']}%)")
    print(f"  di cui su dorsale PRINCIPALE: {r['n_entro_principale']} particelle, "
          f"{r['ha_entro_principale']} ha ({r['pct_ha_entro_principale']}%)")
    print(f"  terra di famiglia nella fascia: {r['ha_famiglia_entro']} ha su "
          f"{r['ha_famiglia']} ({r['pct_famiglia_entro']}%)")
    if r.get('banda_pct'):
        print()
        print(f"  [!] BANDA DI SENSIBILITA': dal {r['banda_pct'][0]}% al {r['banda_pct'][1]}% "
              'degli ettari a seconda delle soglie — il numero singolo non e\' una misura.')
        print("  soglie                                 dorsali   %ha    n.part")
        for s in r['sensibilita']:
            print(f"    {s['etichetta']:<36} {s['dorsali']:>7}  {s['pct_ha_entro']:>5}%  "
                  f"{s['n_particelle_entro']:>5}")
    print()
    print('  ' + r['nota'])
