"""land-scout blocco — dal pool di particelle al BLOCCO CONTIGUO BANCABILE.

Fino alla Fase 31 il tool sapeva dire, particella per particella, quanto vale e
cosa la blocca. Non sapeva rispondere alla domanda che un developer fa davvero:
**"dammi 30 ettari contigui, e dimmi con quante persone devo parlare."**

Questo modulo chiude quel salto. Tre lezioni pagate sul campo a Morcone stanno
dentro il codice, non nei commenti:

1. **I filtri vanno applicati PRIMA della crescita, non dopo.** Crescere su
   terra "idonea" e poi scoprire il bosco significa annunciare 30 ha e averne
   19,6. Qui si cresce solo su particelle gia' ammesse.

2. **Gli ettari sono NETTI.** Bosco vincolato, fasce paesaggistiche e sedime
   dei fabbricati non ospitano moduli: vanno sottratti prima di scrivere un
   numero in un teaser. Le quote vincolate si SOMMANO (non si moltiplicano):
   non sappiamo se si sovrappongono, e la stima prudente e' quella che non
   promette ettari inesistenti.

3. **L'obiettivo non e' l'ettaro, e' la CONTROPARTE.** Dove la terra idonea
   abbonda — ed e' il caso normale — il vincolo non e' la superficie ma il
   numero di firme da raccogliere. Un blocco da 30 ha con 48 proprietari non
   e' bancabile; uno da 20 ha con 16 lo e'.

Uso tipico (dopo scan → catasto → vincoli → occupazione):

    from landscout import blocco
    amm = blocco.ammissibilita(parcels, vinc, occ)
    adj = blocco.adiacenza(amm)
    fr  = blocco.frontiera(amm, adj, targets=(15, 20, 25, 30))
    blk = blocco.cresci_migliore(amm, adj, 20.0, ancore=famiglia)
    print(blocco.print_bancabilita(blocco.bancabilita(blk, d_se_m=4400)))
    blocco.esporta_mappa(blk, 'mappa.html'); blocco.esporta_visure(blk, 'visure.csv')

CLI end-to-end:
    python -m landscout.blocco --parcels pool.json --vincoli v.json \\
        --occupazione o.json --ancore fam.json --target 20 --out-dir ./blocco
"""
import argparse
import csv
import glob
import heapq
import json
import math
import os
from collections import defaultdict

from . import config

# ---------------------------------------------------------------- soglie
# Definite in config.py insieme a tutte le altre: una soglia che vive solo qui e'
# una soglia che nessuno trova quando deve cambiarla.
try:
    from . import config as C
except ImportError:  # eseguito come script sciolto
    import config as C

# Una particella piu' stretta del franco di rispetto non ospita moduli nemmeno
# in teoria; se in piu' e' lunga e sottile e' quasi sempre una STRADA, una
# carraia o un fosso, non un campo. Il layer stradale OSM non basta: le
# interpoderali non sono mappate (Fg69/726, 194x4,8 m, risultava 0% strada).
# La geometria le riconosce lo stesso.
LARGH_MIN_M = 12.5          # = franco di rispetto: sotto, superficie utile nulla
ALLUNGAMENTO_STRADA = 8.0   # lunghezza/larghezza oltre cui e' un nastro, non un fondo

SOGLIE = {
    'bosco_max_pct': C.BLOCCO_BOSCO_MAX_PCT,
    'fascia_max_pct': C.BLOCCO_FASCIA_MAX_PCT,
    'edificato_max_pct': C.BLOCCO_EDIFICATO_MAX_PCT,
    'ha_min_netti': C.BLOCCO_HA_MIN_NETTI,
    'adiacenza_m': C.BLOCCO_ADIACENZA_M,
    'largh_min_m': LARGH_MIN_M,
    'allungamento_strada': ALLUNGAMENTO_STRADA,
    'fascia_strada_max_pct': 70.0,
}
MWP_PER_HA = C.MWP_PER_HA_AGRIPV
MAX_CONTROPARTI = C.BLOCCO_MAX_CONTROPARTI
QUOTA_OSTAGGIO_PCT = C.BLOCCO_QUOTA_OSTAGGIO_PCT


def _id(p):
    return f"{p['fg']}_{p['pla']}"


def _forma(poly, la0=None):
    """Lunghezza massima e larghezza media (area/lunghezza) di un poligono."""
    m = _metrico(poly, la0)
    n = len(m)
    A = abs(sum(m[i][0] * m[(i + 1) % n][1] - m[(i + 1) % n][0] * m[i][1]
                for i in range(n))) / 2
    dmax = max(math.dist(a, b) for a in m for b in m) if n > 1 else 0
    return dmax, (A / dmax if dmax else 0)


def _pct(d, k):
    return (d.get(k) or 0) if d else 0


# ---------------------------------------------------------------- 1. ammissibilita'
def ammissibilita(parcels, vincoli, occupazione, soglie=None, tech='agriPV',
                  fascia_strada=None):
    """Chi entra nel gioco, con quanti ettari NETTI, e chi resta fuori e perche'.

    parcels: [{'fg','pla','ha','poly'}] · vincoli: {id: risultato feasibility}
    occupazione: {id: risultato screening_due_stadi}

    Un dato assente NON e' un dato pulito: senza vincoli o senza occupazione la
    particella e' esclusa come 'non verificata', mai ammessa per default.
    """
    S = dict(SOGLIE, **(soglie or {}))
    ammesse, scarti = [], defaultdict(lambda: {'n': 0, 'ha': 0.0})

    for p in parcels:
        k = _id(p)
        v, o = vincoli.get(k), occupazione.get(k)
        ha = p.get('ha') or 0
        motivo = None

        if v is None or o is None:
            motivo = 'non verificata (manca vincoli o occupazione)'
        elif o.get('verdetto') == 'NON_VERIFICATO':
            motivo = 'occupazione non verificata'
        else:
            b = _pct(v, 'bosco_142g_pct')
            l = _pct(v, 'lago_300m_pct')
            f = _pct(v, 'fiume_150m_pct')
            e = o.get('pct') or 0
            if v.get('habitat_ban'):
                motivo = 'habitat 6210/6220: FV vietato in ZPS (DGR Campania 617/2024)'
            elif v.get('pai_blocker'):
                # P3/P4 frana o P2/P3 idraulica: e' cio' che ha affossato lo screening
                # E-phowi. AA (classe 0) e P1 NON escludono: AA copre meta' del Sannio.
                motivo = (f"PAI frana P{v.get('pai_fr')}" if (v.get('pai_fr') or -1) >= 3
                          else f"PAI idraulica P{v.get('pai_idr')}")
            elif v.get('usi_civici'):
                motivo = 'usi civici (art.142-h)'
            elif v.get('art136') or v.get('archeo_area'):
                motivo = 'vincolo art.136 / area archeologica'
            elif e >= S['edificato_max_pct'] or o.get('verdetto') == 'ESCLUSA':
                motivo = 'edificato/frammento'
            elif (fascia_strada or {}).get(k, 0) > S['fascia_strada_max_pct']:
                # non "una strada accanto" ma "e' tutta banchina": vedi
                # strade.quota_in_fascia()
                motivo = f'fascia stradale {fascia_strada[k]:.0f}%'
            elif b > S['bosco_max_pct']:
                motivo = f'bosco 142-g {b:.0f}%'
            elif l > S['fascia_max_pct']:
                motivo = f'fascia 300 m lago (142-b) {l:.0f}%'
            elif f > S['fascia_max_pct']:
                motivo = f'fascia 150 m fiume (142-c) {f:.0f}%'
            else:
                # forma: un nastro lungo e sottile e' una strada o un fosso, non
                # un fondo. Escluderlo NON contraddice la regola "una striscia
                # dentro il blocco resta utile": quella vale per le strisce di
                # CAMPO, non per la sede stradale, su cui non si costruisce.
                dmax, larg = _forma(p['poly'])
                perso_pct = min(100.0, b + l + f + e)
                netti = ha * (1 - perso_pct / 100.0)
                if (larg and larg < S['largh_min_m'] and dmax > 100
                        and dmax / max(larg, 0.1) > S['allungamento_strada']):
                    motivo = f'nastro {larg:.0f}x{dmax:.0f} m: strada o fosso'
                elif netti < S['ha_min_netti']:
                    motivo = f'netto {netti:.3f} ha'
                else:
                    ammesse.append({
                        'fg': p['fg'], 'pla': p['pla'], 'ha': round(ha, 3),
                        'netti': round(netti, 3), 'poly': p['poly'],
                        'detrazioni': {'bosco_pct': round(b, 1), 'lago_pct': round(l, 1),
                                       'fiume_pct': round(f, 1), 'edificato_pct': round(e, 2)},
                        'zps_pct': round(_pct(v, 'zps_pct'), 1),
                    })
        if motivo:
            g = motivo.split(':')[0].split(' ')[0] if motivo[0].isalpha() else motivo
            key = motivo if len(motivo) < 26 else motivo[:24] + '…'
            scarti[key]['n'] += 1
            scarti[key]['ha'] += ha

    # Cio' che `vincoli` ha dichiarato NON verificato deve arrivare al blocco: la
    # particella entra (non verificato non e' bocciato), ma il riepilogo non puo'
    # tacerlo, altrimenti un blocco costruito senza il PAI sembra un blocco senza
    # frane. E' la stessa regola di `arricchisci`, applicata alle fonti di monte.
    nv = []
    n_pai = sum(1 for a in ammesse if (vincoli.get(_id(a)) or {}).get('pai_ok') is False)
    if n_pai:
        nv.append(f'{n_pai} particelle con PAI frane/idraulica NON verificato '
                  '(IdroGEO non raggiunto): il rischio frana resta da controllare')
    n_sitap = sum(1 for a in ammesse if (vincoli.get(_id(a)) or {}).get('sitap_ok') is False)
    if n_sitap:
        nv.append(f'{n_sitap} particelle con paesaggio/usi civici NON verificati '
                  '(SITAP non raggiunto o non mappato per la regione)')
    return {'ammesse': ammesse, 'scarti': dict(scarti),
            'ha_pool': round(sum((p.get('ha') or 0) for p in parcels), 1),
            'ha_ammessi_lordi': round(sum(a['ha'] for a in ammesse), 1),
            'ha_ammessi_netti': round(sum(a['netti'] for a in ammesse), 1),
            'non_verificati': nv,
            'soglie': S}


def print_ammissibilita(A, top=12):
    print(f"POOL: {A['ha_pool']} ha")
    print('scartate (ha lordi):')
    for k, d in sorted(A['scarti'].items(), key=lambda x: -x[1]['ha'])[:top]:
        print(f"   {k:<40s} {d['n']:5d} part. {d['ha']:8.1f} ha")
    print(f"AMMESSE: {len(A['ammesse'])} part. | {A['ha_ammessi_lordi']} ha lordi "
          f"| {A['ha_ammessi_netti']} ha NETTI")
    for m in (A.get('segnalazioni') or []):
        print(f'   ! {m}')
    for m in (A.get('non_verificati') or []):
        print(f'   ? {m}')


# ------------------------------------------- 0. dallo scan al blocco (il ponte)
def da_scan(path, voto_min=None, classi=('A', 'B', 'C'), comune=None, ha_min=None,
            escludi_blocker=True):
    """L'esito di `scan.py` diventa l'ingresso di `pipeline()`.

    Era il pezzo mancante fra le due meta' del tool: `scan` sa TROVARE la terra
    in un'area qualunque e la vota; `blocco` sa trasformarla in un blocco
    contiguo con un numero di firme. Non si parlavano — il passaggio si faceva a
    mano, e per questo l'estensione fuori dal Sannio non e' mai partita: non
    mancava la copertura dei dati, mancava il tubo.

    Filtra e traduce, non rivaluta: i vincoli li rimisura `pipeline()` sui
    poligoni (lo scan campiona il centroide, che su una particella lunga e' una
    risposta binaria a una domanda continua).

    `escludi_blocker` toglie chi ha gia' un blocco secco nei flag dello scan;
    una particella con il PAI NON verificato invece **resta**, perche' non
    verificato non e' bocciato — sara' `pipeline` a rimisurarla.
    """
    d = json.load(open(path, encoding='utf-8'))
    righe = d.get('risultati') if isinstance(d, dict) else d
    if not righe:
        raise ValueError(f'{path}: nessun risultato di scan')

    senza_geom = [r for r in righe if not r.get('poly')]
    if senza_geom and len(senza_geom) == len(righe):
        raise ValueError(
            f'{path}: nessuna particella ha il perimetro. E uno scan prodotto prima '
            f'dell 08/08/2026: rilanciare scan.py (ora salva anche `poly`), oppure '
            f'ricostruire le geometrie dal catasto.')

    out, scartate = [], {}
    for r in righe:
        if not r.get('poly'):
            scartate['senza geometria'] = scartate.get('senza geometria', 0) + 1
            continue
        if comune and str(r.get('com', '')).upper() != str(comune).upper():
            continue
        if classi and r.get('classe') not in classi:
            scartate[f"classe {r.get('classe')}"] = scartate.get(f"classe {r.get('classe')}", 0) + 1
            continue
        if voto_min is not None and (r.get('voto') or 0) < voto_min:
            scartate[f'voto < {voto_min}'] = scartate.get(f'voto < {voto_min}', 0) + 1
            continue
        if ha_min is not None and (r.get('ha') or 0) < ha_min:
            scartate[f'sotto {ha_min} ha'] = scartate.get(f'sotto {ha_min} ha', 0) + 1
            continue
        if escludi_blocker and any('BLOCKER' in f or 'vietato' in f.lower()
                                   for f in (r.get('flags') or [])):
            scartate['blocker nello scan'] = scartate.get('blocker nello scan', 0) + 1
            continue
        out.append({'fg': str(r['fg']), 'pla': str(r['pla']), 'ha': r.get('ha') or 0,
                    'poly': [tuple(q) for q in r['poly']],
                    'lat': r.get('lat'), 'lon': r.get('lon'), 'com': r.get('com'),
                    'voto_scan': r.get('voto'), 'classe_scan': r.get('classe')})
    return {'parcels': out, 'scartate': scartate, 'n_in': len(righe), 'n_out': len(out),
            'senza_geometria': len(senza_geom),
            'nota': ('lo scan vota sul CENTROIDE: qui serve solo a scremare. '
                     'I vincoli veri li rimisura pipeline() sui poligoni.')}


# ------------------------------------------------- 1-bis. arricchimento di A
# I quattro moduli chiamati qui sono nati fra il 22/07 e il 2/08 perche' la loro
# assenza aveva gia' prodotto numeri sbagliati sul campo: la chioma vera (30 ha
# annunciati, 19,6 reali), gli uliveti di famiglia, la fascia dei crinali del
# PTCP (il motivo per cui la Provincia ha impugnato il PAUR di Pontelandolfo), il
# buffer 500 m dai beni tutelati. Fino all'audit dell'08/08/2026 nessun punto di
# ingresso li chiamava: giravano solo se ci si ricordava di lanciarli a mano.
# Un controllo che dipende dalla memoria dell'operatore e' un controllo che salta.
#
# Stanno PRIMA della crescita, non dentro esporta(), per la lezione della Fase 32:
# crescere su terra "idonea" e scoprire il bosco dopo significa annunciare 30
# ettari e averne 19,6.
def _particelle_di(A):
    return [a for a in A['ammesse'] if a.get('poly')]


def _modulo(nome, _moduli):
    """Import pigro, sostituibile nei test (i quattro moduli parlano con la rete).

    Gli import sono scritti per esteso, e non con `import_module(nome)`, perche' il
    collegamento deve essere VISIBILE a chi legge il codice e a chi lo analizza:
    `qa_integrazione` ricostruisce il grafo degli import con `ast` per accorgersi
    se un modulo torna orfano, e un import dinamico gli sarebbe invisibile —
    cioe' il controllo che impedisce il difetto lo nasconderebbe.
    """
    if _moduli and nome in _moduli:
        return _moduli[nome]
    from . import chioma, coltura, crinali, fuoco, idonee, prossimita
    return {'chioma': chioma, 'coltura': coltura, 'crinali': crinali,
            'fuoco': fuoco, 'idonee': idonee, 'prossimita': prossimita}[nome]


def arricchisci(A, prov=None, visure_dir=None, chioma=True, coltura=True,
                prossimita=True, crinali=None, idonee=True, fuoco=True,
                verbose=True, _moduli=None):
    """Applica ad A i controlli che cambiano gli ettari netti o li mettono in dubbio.

    Ogni controllo puo' fallire (sono tutti in rete). La regola e' sempre la
    stessa: **un controllo che non gira lascia una riga**, in `A['non_verificati']`,
    e da li' finisce nei rischi di bancabilita'. Non esiste il silenzio.

    `crinali=None` significa "solo dove la regola esiste": la fascia di rispetto
    e' del PTCP di Benevento (art. 32), altrove non e' mappata e non si applica —
    ma il fatto va detto, non sottinteso.
    """
    non_ver = list(A.get('non_verificati') or [])
    segn = list(A.get('segnalazioni') or [])
    part = _particelle_di(A)
    if len(part) < len(A['ammesse']):
        non_ver.append(f'{len(A["ammesse"]) - len(part)} particelle senza geometria: '
                       'chioma, prossimita e crinali non le hanno potute misurare')

    if chioma:
        try:
            CH = _modulo('chioma', _moduli)
            R = CH.screening({_id(a): {'anello': a['poly'], 'ha': a['ha']} for a in part},
                             verbose=False)
            A = CH.applica(A, R)
            c = A.get('chioma') or {}
            if c.get('ha_sottratti'):
                segn.append(f"chioma reale: -{c['ha_sottratti']} ha netti su "
                            f"{c.get('ridotte', 0)} particelle (Copernicus TCD)")
            if c.get('non_misurate'):
                non_ver.append(f"{c['non_misurate']} particelle con copertura arborea "
                               'NON misurata: gli ettari netti li' + "'" + ' sono un massimo')
        except Exception as e:
            non_ver.append(f'copertura arborea NON verificata ({type(e).__name__}): '
                           'il bosco vero non e nei vincoli, e toglie ettari')

    if coltura and visure_dir:
        try:
            CO = _modulo('coltura', _moduli)
            pdf = sorted(glob.glob(os.path.join(visure_dir, '*.pdf')))
            col = CO.leggi_visure(pdf)
            A = CO.applica(A, col)
            c = A.get('coltura') or {}
            if c.get('ha_sottratti'):
                segn.append(f"colture arboree (uliveto/vigneto): -{c['ha_sottratti']} ha "
                            f"netti su {c.get('ridotte', 0)} particelle")
            if c.get('senza_dato'):
                non_ver.append(f"{c['senza_dato']} particelle senza dato di coltura")
        except Exception as e:
            non_ver.append(f'colture NON lette dalle visure ({type(e).__name__}): '
                           'uliveti e vigneti restano contati come terra libera')
    elif coltura:
        non_ver.append('colture NON verificate: nessuna cartella visure indicata '
                       '(un uliveto pesa quanto un vincolo, ma non sta in nessun layer)')

    if prossimita and part:
        PR = None
        try:
            PR = _modulo('prossimita', _moduli)
        except Exception as e:
            non_ver.append(f'controlli di prossimita non disponibili ({type(e).__name__})')
        if PR is not None:
            _prossimita_su(A, part, PR, segn, non_ver)

    # il lato POSITIVO: non solo cosa blocca, ma dove l'iter e' agevolato.
    # Non toglie ettari e non ne aggiunge: cambia i tempi, ed e' la prima cosa
    # che guarda un developer quando sceglie fra due terreni equivalenti.
    if idonee and part:
        try:
            ID = _modulo('idonee', _moduli)
            R = ID.valuta(part, ID.innesco(part))
            A = ID.applica(A, R)
            if R['n_candidate']:
                tipi = sorted({c['tipo'] for v in R['particelle'].values()
                               for c in v['criteri']})
                segn.append(f"{R['n_candidate']}/{R['n_totale']} particelle CANDIDATE "
                            f"ad area idonea ({', '.join(tipi)}): iter accelerato, "
                            f"da confermare sulla piattaforma GSE areeidonee.gse.it")
        except Exception as e:
            non_ver.append(f'aree idonee NON verificate ({type(e).__name__}): '
                           'un eventuale iter accelerato resta ignoto')

    # aree percorse dal fuoco: e' il vincolo che non compare in nessuna
    # cartografia e che, se morde, uccide il progetto per 10-15 anni.
    if fuoco and part:
        try:
            FU = _modulo('fuoco', _moduli)
            R = FU.storico(part)
            A = FU.applica(A, R)
            for r in FU.rischi(R):
                (segn if 'percorsa dal fuoco' in r else non_ver).append(r)
        except Exception as e:
            non_ver.append(f'aree percorse dal fuoco NON verificate ({type(e).__name__}): '
                           'il divieto della L. 353/2000 dura 10-15 anni e non sta in '
                           'nessun layer di vincolo')

    fascia = crinali if crinali is not None else (config.norm_prov(prov) == 'BN')
    if fascia and part:
        try:
            CR = _modulo('crinali', _moduli)
            r = CR.fascia_crinali(part)
            if not r.get('verificato'):
                non_ver.append(f"fascia crinali NON verificata: {r.get('motivo')}")
            else:
                _segna(A, r['particelle'], 'crinale',
                       lambda v: v.get('entro_buffer'))
                if r.get('n_entro'):
                    segn.append(
                        f"{r['n_entro']}/{r['n_totale']} particelle nella fascia di rispetto "
                        f"dei crinali (PTCP BN art. 32, {r['buffer_m']:.0f} m): "
                        f"{r.get('n_entro_principale', 0)} su dorsale principale — "
                        'e il motivo del ricorso della Provincia sul PAUR di Pontelandolfo')
        except Exception as e:
            non_ver.append(f'fascia crinali NON verificata ({type(e).__name__})')
    elif crinali is None and part:
        non_ver.append(f'fascia crinali non applicata: la regola mappata e quella del PTCP '
                       f'di Benevento e la provincia qui e {config.norm_prov(prov) or "ignota"}')

    A = dict(A, non_verificati=non_ver, segnalazioni=segn)
    return A


def _segna(A, per_particella, campo, cond, valore=None):
    """Scrive un flag sulle ammesse, senza toccare gli ettari.

    I controlli di distanza (beni tutelati, corridoio, crinali) **segnalano e non
    decidono**: il perimetro vincolato vero sta nel decreto di tutela o nella
    tavola del piano, non in OSM ne' in un DEM. Detrarre ettari su questa base
    sarebbe inventare precisione.
    """
    leggi = valore or (lambda v: v.get('d_m', True))
    for a in A['ammesse']:
        v = per_particella.get(_id(a))
        if v is None:
            continue
        a[campo] = leggi(v)
        if cond(v):
            a[campo + '_critico'] = True


def _prossimita_su(A, part, PR, segn, non_ver):
    try:
        b = PR.beni_tutelati(part)
        _segna(A, b['particelle'], 'd_bene_tutelato_m', lambda v: v.get('entro_buffer'))
        if b['n_entro']:
            segn.append(f"{b['n_entro']} particelle entro {b['buffer_m']:.0f} m da un "
                        f"possibile bene tutelato (DM 21/06/2024): da verificare sul "
                        f"decreto di tutela, non sul nome OSM")
    except Exception as e:
        non_ver.append(f'buffer 500 m dai beni tutelati NON verificato ({type(e).__name__})')
    try:
        c = PR.corridoio(part)
        _segna(A, c['particelle'], 'd_corridoio_m', lambda v: v.get('entro_buffer'))
        if c['n_entro']:
            segn.append(f"{c['n_entro']} particelle entro {c['buffer_m']:.0f} m dall'asta "
                        f"principale ({', '.join(c['corsi'][:3])}): corridoio ecologico "
                        f"da leggere sul PTR/PTCP")
    except Exception as e:
        non_ver.append(f'corridoio ecologico NON verificato ({type(e).__name__})')
    try:
        p = PR.pendenza(part)
        _segna(A, p['particelle'], 'pendenza_pct', lambda v: v.get('oltre_limite'),
               valore=lambda v: v.get('pendenza_pct'))
        if p['n_oltre_limite']:
            segn.append(f"{p['n_oltre_limite']} particelle oltre il {p['limite_pct']:.0f}% "
                        'di pendenza: strutture e movimento terra fuori budget')
        if p['n_non_verificate']:
            non_ver.append(f"{p['n_non_verificate']} particelle con pendenza NON verificata")
    except Exception as e:
        non_ver.append(f'pendenza NON verificata ({type(e).__name__}): sopra il 15% '
                       'il costo delle strutture mangia il margine')


# ---------------------------------------------------------------- 2. adiacenza
def _metrico(poly, la0=None):
    """Proiezione piana locale.

    ⚠️ `la0` DEVE essere lo stesso per tutti i poligoni che verranno confrontati
    fra loro. Usare la latitudine del primo vertice di ciascun poligono (com'era
    fino al 20/07) significa proiettare ogni particella con un fattore di scala
    diverso: la stessa longitudine finisce in x diverse, ~38 m di scarto ogni
    0,002 gradi di latitudine, fino a ~380 m sull'estensione di un comune. Con una
    soglia di adiacenza di 15 m questo spezza blocchi realmente contigui.
    """
    if la0 is None:
        la0 = poly[0][0]
    k = 111320 * math.cos(math.radians(la0))
    return [(q[1] * k, q[0] * 110540) for q in poly]


def adiacenza(A, thr_m=None):
    """Grafo di contiguita' fra particelle ammesse.

    Soglia in metri (default 15): due fondi separati da una stradina interpoderale
    o da un fosso restano un blocco unico agli occhi di chi progetta l'impianto.
    Griglia spaziale per non fare 1.300x1.300 confronti di poligoni.
    """
    thr = thr_m if thr_m is not None else SOGLIE['adiacenza_m']
    P = A['ammesse'] if isinstance(A, dict) else A
    if not P:
        return defaultdict(set)
    # una sola origine di proiezione per tutto l'insieme: vedi _metrico()
    lats = [q[0] for p in P for q in p['poly']]
    la0 = (min(lats) + max(lats)) / 2
    MP = [_metrico(p['poly'], la0) for p in P]
    BB = [(min(x for x, y in m), min(y for x, y in m),
           max(x for x, y in m), max(y for x, y in m)) for m in MP]
    cell = max(60.0, thr * 4)
    grid = defaultdict(list)
    # ⚠️ 12/08/2026: il bbox va DILATATO di `thr` prima di indicizzarlo. Senza,
    # due particelle distanti 4 m ma separate da una linea della griglia non
    # finiscono mai in una cella comune e non vengono nemmeno confrontate:
    # l'arco sparisce, il blocco si spezza, e `componenti` riporta due isole
    # dove ce n'e' una. Non e' un caso raro — dipende solo da dove cade il
    # confine della cella rispetto alle coordinate assolute, quindi e' una
    # lotteria: su una griglia sintetica 6x6 si perdeva una colonna intera di
    # archi (36 particelle contigue lette come 4 isole).
    for i, b in enumerate(BB):
        for gx in range(int((b[0] - thr) // cell), int((b[2] + thr) // cell) + 1):
            for gy in range(int((b[1] - thr) // cell), int((b[3] + thr) // cell) + 1):
                grid[(gx, gy)].append(i)

    t2 = thr * thr
    adj = defaultdict(set)
    for ids in grid.values():
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                i, j = ids[a], ids[b]
                if j in adj[i]:
                    continue
                x0, y0, x1, y1 = BB[i]
                u0, v0, u1, v1 = BB[j]
                if x0 > u1 + thr or u0 > x1 + thr or y0 > v1 + thr or v0 > y1 + thr:
                    continue
                if any((px - qx) ** 2 + (py - qy) ** 2 < t2
                       for px, py in MP[i] for qx, qy in MP[j]):
                    adj[i].add(j)
                    adj[j].add(i)
    return adj


def componenti(A, adj):
    """Blocchi contigui gia' esistenti, dal piu' grande. Serve a sapere in quale
    'isola' si sta lavorando prima di sperare in un target irraggiungibile."""
    P = A['ammesse'] if isinstance(A, dict) else A
    par = list(range(len(P)))

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    for i, js in adj.items():
        for j in js:
            par[find(i)] = find(j)
    comp = defaultdict(list)
    for i in range(len(P)):
        comp[find(i)].append(i)
    return sorted(comp.values(), key=lambda c: -sum(P[i]['netti'] for i in c))


# ---------------------------------------------------------------- 3. crescita
def cresci(A, adj, seed, target_ha, ancore=None):
    """Crescita greedy da un seme fino al target di ettari NETTI.

    `ancore` = indici di particelle gia' controllate (terra propria): entrano per
    prime perche' costano zero trattative. Fra le altre vince la piu' grande:
    ogni particella aggiunta e' una controparte, quindi si comprano ettari, non
    pezzi di carta.
    """
    P = A['ammesse'] if isinstance(A, dict) else A
    anc = set(ancore or ())
    sel = {seed}
    tot = P[seed]['netti']
    front = set(adj[seed])
    while tot < target_ha and front:
        b = max(front, key=lambda i: (i in anc, P[i]['netti']))
        sel.add(b)
        tot += P[b]['netti']
        front.discard(b)
        front |= (adj[b] - sel)
    return sel, round(tot, 2)


def cresci_cercando(A, adj, seed, target_ha, ancore):
    """Crescita che VA A CERCARE le ancore invece di aspettare che tocchino il fronte.

    La greedy di `cresci()` guarda solo i vicini immediati: se una tua particella
    sta due fondi piu' in la', non la vede mai e cresce da un'altra parte. A
    Morcone questo lasciava fuori 9 particelle di famiglia su 22 — e il blocco
    risultante costava anche PIU' acquisti, perche' cresceva a caso invece che
    verso un obiettivo.

    Qui a ogni passo si chiede: *qual e' l'ancora piu' economica da raggiungere?*
    Costo di un cammino = quante particelle NUOVE DI TERZI servono per arrivarci
    (le ancore costano 0: sono gia' tue). Dijkstra su questo costo, si assorbe
    tutto il cammino, si ripete. Quando le ancore finiscono, si torna a prendere
    la vicina piu' grande.

    Non e' sempre meglio della greedy — ma quando le ancore sono sparse a
    grappoli, cioe' il caso normale di una proprieta' agricola ereditata, lo e'
    su entrambi i fronti: piu' terra tua dentro E meno controparti.
    """
    P = A['ammesse'] if isinstance(A, dict) else A
    anc = set(ancore or ())
    sel = {seed}
    tot = P[seed]['netti']
    while tot < target_ha:
        vis = set()
        pq = [(0, i, ()) for i in sel]
        heapq.heapify(pq)
        best = None
        while pq:
            c, u, path = heapq.heappop(pq)
            if u in vis:
                continue
            vis.add(u)
            if u in anc and u not in sel:
                best = (c, u, path)
                break
            for v in adj[u]:
                if v not in vis:
                    heapq.heappush(pq, (c + (0 if v in anc else 1), v, path + (v,)))
        if best is None:
            front = set().union(*[adj[i] for i in sel]) - sel if sel else set()
            if not front:
                break
            b = max(front, key=lambda i: P[i]['netti'])
            sel.add(b)
            tot += P[b]['netti']
            continue
        _, u, path = best
        for v in path + (u,):
            if v not in sel:
                sel.add(v)
                tot += P[v]['netti']
    return sel, round(tot, 2)


def pota(A, adj, sel, target_ha, ancore=None, tolleranza=1.0):
    """Toglie dal blocco le particelle che costano piu' di quanto rendono.

    `cresci` e' greedy pura: aggiunge e non toglie mai. Il risultato e' che per
    arrivare al target si tira dentro qualunque cosa tocchi il fronte, comprese
    decine di fazzoletti da 500 mq — e ogni fazzoletto e' una **firma**, cioe'
    un proprietario da trovare, convincere e portare dal notaio. Sul portafoglio
    di Morcone questo produceva un blocco da 20,21 ha che costava **38 firme**:
    esiste sulla mappa, non esiste come trattativa.

    Qui si fa il passo che mancava. Si rimuove, una alla volta, la particella di
    TERZI piu' piccola la cui uscita:
      · non porta il blocco sotto il target,
      · non lo spezza in due (la contiguita' e' il blocco).
    Le ancore non si toccano mai: sono gratis, e sono il motivo per cui il blocco
    esiste. Si ripete finche' non c'e' piu' niente da togliere.

    Non e' un'ottimizzazione elegante — e' quella che serve: riduce il numero di
    controparti a parita' di ettari, che e' l'unica leva vera sul costo di
    aggregazione.
    """
    P = A['ammesse'] if isinstance(A, dict) else A
    anc = set(ancore or ())
    sel = set(sel)
    tot = sum(P[i]['netti'] for i in sel)
    soglia = target_ha * tolleranza
    tolte = []

    def connesso(s):
        if len(s) <= 1:
            return True
        avvio = next(iter(s))
        visti = {avvio}
        coda = [avvio]
        while coda:
            u = coda.pop()
            for v in adj.get(u, ()):
                if v in s and v not in visti:
                    visti.add(v)
                    coda.append(v)
        return len(visti) == len(s)

    while True:
        # dalla piu' piccola: e' quella che porta via meno ettari per la firma
        # che fa risparmiare.
        # ⚠️ serve un flag esplicito: con `for/else` il `break` per "nessun
        # candidato abbastanza piccolo" saltava l'`else` e il `while` ripartiva
        # identico — ciclo infinito. Preso da qa_blocco al primo lancio.
        rimosso = False
        for i in sorted((i for i in sel if i not in anc), key=lambda i: P[i]['netti']):
            if tot - P[i]['netti'] < soglia:
                break            # le successive sono piu' grandi: inutile provare
            if connesso(sel - {i}):
                sel.discard(i)
                tot -= P[i]['netti']
                tolte.append(i)
                rimosso = True
                break
        if not rimosso:
            break
    return sel, round(tot, 2), tolte


def _pack(A, sel, tot, ancore, titolo):
    P = A['ammesse'] if isinstance(A, dict) else A
    anc = set(ancore or ())
    part = []
    for i in sorted(sel, key=lambda i: -P[i]['netti']):
        d = dict(P[i])
        d['ancora'] = i in anc
        part.append(d)
    return {'titolo': titolo, 'n': len(sel), 'ha_netti': tot,
            'ha_lordi': round(sum(p['ha'] for p in part), 2),
            'ha_ancore': round(sum(p['netti'] for p in part if p['ancora']), 2),
            'n_ancore': sum(1 for p in part if p['ancora']),
            'n_acquisti': sum(1 for p in part if not p['ancora']),
            'ha_acquisti': round(sum(p['netti'] for p in part if not p['ancora']), 2),
            'particelle': part}


def cresci_migliore(A, adj, target_ha, ancore=None, semi=None, tolleranza=0.98,
                    obiettivo='ancore', potatura=True, sovracrescita=1.0):
    """Prova molti semi e tiene il blocco migliore.

    obiettivo='ancore'   → massimizza la terra gia' tua dentro il blocco
    obiettivo='controparti' → minimizza il numero di proprietari da convincere
    potatura=True        → dopo la crescita toglie le particelle di terzi
                           superflue (v. `pota`): stessi ettari, meno firme
    """
    P = A['ammesse'] if isinstance(A, dict) else A
    anc = set(ancore or ())
    if semi is None:
        semi = sorted(anc) if (anc and obiettivo == 'ancore') else \
            sorted(range(len(P)), key=lambda i: -P[i]['netti'])[:50]
    # Con obiettivo 'ancore' si provano ENTRAMBE le strategie e vince la migliore:
    # la greedy locale batte quella che cerca quando le ancore sono gia' in fila,
    # e non c'e' motivo di indovinare in anticipo quale delle due sia il caso.
    strategie = [cresci]
    if anc and obiettivo == 'ancore':
        strategie.append(cresci_cercando)

    # SOVRACRESCITA: `sovracrescita>1` fa crescere il blocco oltre il target per
    # dare margine alla potatura — l'idea e' scambiare i fazzoletti raccolti per
    # strada con particelle grandi a parita' di ettari. Sul pool vero di Morcone
    # (562 particelle ammesse, 225,7 ha, 5 blocchi da 20 ha) la misura dice che
    # **peggiora**, e di molto:
    #     sovracrescita 1,00 → 141 firme · 0,72 ha/firma   <- default
    #     sovracrescita 1,25 → 163 firme · 0,66 ha/firma
    #     sovracrescita 1,50 → 185 firme · 0,56 ha/firma
    #     sovracrescita 2,00 → 201 firme · 0,55 ha/firma
    # Il motivo: nel catasto frammentato i fazzoletti non sono zavorra, sono i
    # PONTI che tengono unito il blocco, e la potatura non puo' toglierli senza
    # spezzarlo. Crescere di piu' ne raccoglie altri e non ne libera nessuno.
    # Resta come parametro perche' su un catasto a maglia larga il ragionamento
    # potrebbe reggere — ma di default e' spento, e chi lo alza deve misurare.
    obiettivo_crescita = target_ha * (sovracrescita if potatura else 1.0)
    best = None
    for f in strategie:
        for s in semi:
            sel, tot = f(A, adj, s, obiettivo_crescita, ancore=anc)
            if tot < target_ha * tolleranza:
                sel, tot = f(A, adj, s, target_ha, ancore=anc)
            if tot < target_ha * tolleranza:
                continue
            ha_anc = sum(P[i]['netti'] for i in sel if i in anc)
            nacq = sum(1 for i in sel if i not in anc)
            chiave = (ha_anc, -nacq) if obiettivo == 'ancore' else (-nacq, ha_anc)
            if best is None or chiave > best[0]:
                best = (chiave, sel, tot, s)
    if best is None:
        return None
    _, sel, tot, s = best
    # POTATURA sul VINCITORE, non su ogni candidato: potare tutti costa un BFS per
    # ogni rimozione per ogni seme per ogni strategia, e sul pool di Morcone (562
    # particelle, 50 semi, 2 strategie, 5 blocchi) non finisce in dieci minuti.
    # Il prezzo dichiarato: il confronto fra candidati avviene sui blocchi non
    # potati, quindi la scelta del seme resta quella di prima — la potatura
    # migliora il blocco scelto, non la scelta.
    tolte = []
    if potatura:
        # soglia della potatura = il TARGET, non la tolleranza di accettazione.
        # `tolleranza` dice quanto sotto il target un blocco e' ancora accettabile
        # (0,98, e nel portafoglio 0,55): usarla anche qui faceva sfoltire il
        # blocco fino al minimo accettabile invece che fino al target — su Morcone
        # cinque blocchi da 20 ha scendevano a 11. La potatura toglie il
        # superfluo, non gli ettari.
        sel, tot, tolte = pota(A, adj, sel, target_ha, ancore=anc, tolleranza=1.0)
    t = (f"blocco {tot:.1f} ha netti — {len(sel)} particelle "
         f"(seed Fg{P[s]['fg']}/{P[s]['pla']}, obiettivo {obiettivo}"
         + (f", potate {len(tolte)}" if tolte else '') + ")")
    b = _pack(A, sel, tot, anc, t)
    b['potate'] = len(tolte)
    return b


def copri_ancore(A, adj, ancore, max_ponte=8, titolo='blocco famiglia'):
    """Blocchi contigui che contengono TUTTA la terra gia' controllata.

    `cresci_migliore` risponde a "dammi N ettari contigui, preferendo le ancore":
    va benissimo per un developer, ma per un proprietario e' la domanda
    sbagliata. Chi possiede la terra vuole **vendere la propria**, non aggregare
    per conto di altri — e su Morcone la differenza e' netta: il blocco da 35 ha
    piu' facile da mettere insieme conteneva 2,50 ha di famiglia su 9,88
    disponibili, cioe' il 7%.

    Qui il vincolo si rovescia: le ancore sono **obbligatorie**, il resto e'
    solo il collante necessario a renderle contigue. E' un problema di albero di
    Steiner, risolto in modo greedy: si parte dall'ancora piu' grande e si
    attira via via l'ancora non ancora collegata che costa meno particelle di
    terzi, aggiungendo il cammino minimo.

    **`max_ponte`** e' il giudizio che non va nascosto: se per unire un'ancora
    servono piu' di N particelle di estranei, quel ponte costa piu' firme di
    quanto valga la terra che collega, e conviene **un blocco separato**. Da qui
    i sotto-blocchi: non sono un ripiego, sono la risposta onesta quando la terra
    di famiglia non e' contigua. `None` = collega sempre, a qualunque costo.

    Ritorna {'blocchi': [...], 'ancore_coperte', 'ancore_fuori', 'ponti', 'nota'}.
    """
    P = A['ammesse'] if isinstance(A, dict) else A
    anc = sorted(set(ancore or ()), key=lambda i: -P[i]['netti'])
    if not anc:
        raise ValueError('nessuna ancora: copri_ancore serve a coprire la terra propria')

    # componenti: ogni ancora sta in una sola, e ancore di componenti diverse
    # non potranno MAI stare nello stesso blocco (non e' una scelta, e' la mappa)
    comp = componenti(A, adj)
    dove = {}
    for n, c in enumerate(comp):
        for i in c:
            dove[i] = n
    per_comp = defaultdict(list)
    for i in anc:
        if i in dove:
            per_comp[dove[i]].append(i)

    blocchi, ponti_tot, note = [], 0, []
    for n, ancs in sorted(per_comp.items(), key=lambda x: -sum(P[i]['netti'] for i in x[1])):
        gruppi = _steiner(P, adj, ancs, max_ponte)
        for sel, ponte in gruppi:
            ponti_tot += ponte
            tot = round(sum(P[i]['netti'] for i in sel), 2)
            blk = _pack(A, sel, tot, [i for i in sel if i in set(anc)],
                        f"{titolo}: {tot} ha netti — {len(sel)} particelle "
                        f"({sum(1 for i in sel if i in set(anc))} gia' tue)")
            blk['ponte_particelle'] = ponte
            blocchi.append(blk)

    blocchi.sort(key=lambda b: -b['ha_netti'])
    coperte = sum(b['n_ancore'] for b in blocchi)
    fuori = [i for i in anc if i not in dove]
    if len(blocchi) > 1:
        note.append(f'{len(blocchi)} blocchi separati: unirli avrebbe richiesto piu di '
                    f'{max_ponte} particelle di terzi per ponte, cioe piu firme di quanto '
                    f'valga la terra collegata')
    if fuori:
        note.append(f'{len(fuori)} ancore fuori da ogni componente ammissibile: '
                    f'non sono collegabili a nulla')
    return {'blocchi': blocchi, 'n_blocchi': len(blocchi),
            'ancore_coperte': coperte, 'ancore_totali': len(anc),
            'ancore_fuori': fuori, 'ponti': ponti_tot,
            'ha_ancore': round(sum(b['ha_ancore'] for b in blocchi), 2),
            'ha_totali': round(sum(b['ha_netti'] for b in blocchi), 2),
            'note': note,
            'nota': ('le ancore sono obbligatorie: le particelle di terzi qui dentro '
                     'servono SOLO a renderle contigue. Per allargare a un target di '
                     'ettari si cresce dopo, da questo insieme.')}


def _steiner(P, adj, ancore, max_ponte):
    """Collega le ancore col minor numero di particelle di terzi (greedy).

    Ritorna [(insieme_di_indici, particelle_di_ponte), ...]: piu' di uno quando
    un collegamento sarebbe costato piu' di `max_ponte`.
    """
    anc = set(ancore)
    gruppi = []
    da_fare = set(anc)
    while da_fare:
        seme = max(da_fare, key=lambda i: P[i]['netti'])
        sel, ponte = {seme}, 0
        da_fare.discard(seme)
        while True:
            cammino = _cammino_verso(adj, sel, da_fare, anc)
            if cammino is None:
                break
            costo = sum(1 for i in cammino if i not in anc and i not in sel)
            if max_ponte is not None and costo > max_ponte:
                break                       # meglio un blocco separato
            sel |= set(cammino)
            ponte += costo
            da_fare -= sel
        gruppi.append((sel, ponte))
    return gruppi


def _cammino_verso(adj, sorgenti, obiettivi, ancore):
    """BFS a costo unitario sulle particelle di TERZI: le ancore costano zero.

    Si cerca il collegamento che aggiunge meno FIRME, non meno metri: due
    particelle lontane ma di un solo proprietario valgono meno di tre vicine di
    tre proprietari diversi.
    """
    if not obiettivi:
        return None
    import heapq
    dist, prev = {}, {}
    coda = []
    for s in sorgenti:
        dist[s] = 0
        heapq.heappush(coda, (0, s))
    while coda:
        d, u = heapq.heappop(coda)
        if d > dist.get(u, 1e9):
            continue
        if u in obiettivi:
            cammino, x = [], u
            while x is not None:
                cammino.append(x)
                x = prev.get(x)
            return cammino
        for v in adj[u]:
            w = 0 if v in ancore else 1
            if d + w < dist.get(v, 1e9):
                dist[v] = d + w
                prev[v] = u
                heapq.heappush(coda, (d + w, v))
    return None


def print_copertura(R, top=8):
    L = [f"COPERTURA DELLA TERRA DI FAMIGLIA: {R['ancore_coperte']}/{R['ancore_totali']} "
         f"particelle in {R['n_blocchi']} blocco/i · {R['ha_ancore']} ha tuoi su "
         f"{R['ha_totali']} ha totali · {R['ponti']} particelle di ponte"]
    for b in R['blocchi'][:top]:
        quota = 100 * b['ha_ancore'] / b['ha_netti'] if b['ha_netti'] else 0
        L.append(f"  {b['ha_netti']:6.2f} ha netti · {b['n']:3d} part. · "
                 f"tue {b['ha_ancore']:5.2f} ha ({quota:.0f}%) · "
                 f"da acquisire {b['n_acquisti']:3d} · ponte {b['ponte_particelle']}")
    for x in R['note']:
        L.append(f'  ! {x}')
    L.append('  ' + R['nota'])
    return '\n'.join(L)


def frontiera(A, adj, targets=(10, 15, 20, 25, 30, 35, 40), ancore=None):
    """Quanto costa in CONTROPARTI ogni ettaro in piu'.

    E' la tabella che fa prendere la decisione: quasi sempre esiste un ginocchio
    oltre il quale si comprano pochi ettari al prezzo di molte firme.
    """
    righe = []
    prec = None
    for T in targets:
        senza = cresci_migliore(A, adj, T, ancore=None, obiettivo='controparti')
        con = cresci_migliore(A, adj, T, ancore=ancore, obiettivo='ancore') if ancore else None
        r = {'target': T,
             'min_part': senza['n'] if senza else None,
             'min_ha': senza['ha_netti'] if senza else None,
             'con_part': con['n'] if con else None,
             'con_ha': con['ha_netti'] if con else None,
             'ha_ancore': con['ha_ancore'] if con else None,
             'acquisti': con['n_acquisti'] if con else (senza['n'] if senza else None)}
        base = con or senza
        if prec and base and prec[1]:
            d_ha = base['ha_netti'] - prec[1]['ha_netti']
            d_ac = r['acquisti'] - prec[0]
            r['ha_per_controparte'] = round(d_ha / d_ac, 2) if d_ac else None
        if base:
            prec = (r['acquisti'], base)
        righe.append(r)
    return righe


def print_frontiera(righe):
    print(f"{'target':>6} | {'min part':>8} {'ha':>7} | {'con ancore':>10} {'ha':>7} "
          f"{'ha tuoi':>8} {'acquisti':>8} | {'ha/controparte':>14}")
    for r in righe:
        mp = f"{r['min_part']:>8}" if r['min_part'] else ' ' * 8
        mh = f"{r['min_ha']:>7.1f}" if r['min_ha'] else ' ' * 7
        cp = f"{r['con_part']:>10}" if r['con_part'] else ' ' * 10
        ch = f"{r['con_ha']:>7.1f}" if r['con_ha'] else ' ' * 7
        ca = f"{r['ha_ancore']:>8.2f}" if r['ha_ancore'] is not None else ' ' * 8
        ac = f"{r['acquisti']:>8}" if r['acquisti'] else ' ' * 8
        hc = f"{r['ha_per_controparte']:>14.2f}" if r.get('ha_per_controparte') else ' ' * 14
        print(f"{r['target']:>6} | {mp} {mh} | {cp} {ch} {ca} {ac} | {hc}")


# ---------------------------------------------------------------- 4. bancabilita'
def bancabilita(blk, d_se_m=None, mwp_per_ha=MWP_PER_HA, adj=None, A=None):
    """Il blocco regge davanti a una banca? Non un voto: un elenco di ostacoli.

    Il rischio che nessuno guarda e' l'**OSTAGGIO**: se un solo proprietario
    controlla una fetta grossa del blocco, quel proprietario ha diritto di veto
    sul progetto intero e lo sa. Finche' non si conoscono gli intestatari il
    calcolo si fa per particella — limite superiore ottimistico, dichiarato.
    """
    part = blk['particelle']
    ha = blk['ha_netti']
    acq = [p for p in part if not p['ancora']]
    n_acq = len(acq)
    ha_acq = sum(p['netti'] for p in acq)

    ord_acq = sorted(acq, key=lambda p: -p['netti'])
    cum = 0
    n80 = 0
    for p in ord_acq:
        cum += p['netti']
        n80 += 1
        if ha_acq and cum >= 0.8 * ha_acq:
            break
    quota_max = round(100 * ord_acq[0]['netti'] / ha, 1) if ord_acq and ha else 0.0

    rischi, punti = [], []
    if n_acq == 0:
        punti.append('nessuna acquisizione necessaria: blocco interamente controllato')
    else:
        media = ha_acq / n_acq
        if media < 0.5:
            rischi.append(f'frammentazione alta: {media:.2f} ha per controparte '
                          f'({n_acq} trattative per {ha_acq:.1f} ha)')
        else:
            punti.append(f'{media:.2f} ha per controparte')
        if n_acq > MAX_CONTROPARTI:
            rischi.append(f'{n_acq} controparti: sopra la soglia in cui un developer '
                          f'si tira indietro per costo di aggregazione')
        if quota_max >= QUOTA_OSTAGGIO_PCT:
            rischi.append(f'rischio ostaggio: una sola particella vale il {quota_max:.0f}% '
                          f'del blocco — quel proprietario ha veto di fatto')
        punti.append(f"l'80% degli ettari da acquisire sta in {n80} particelle su {n_acq}")

    if blk['ha_ancore'] > 0:
        punti.append(f"ancoraggio: {blk['ha_ancore']:.2f} ha gia' controllati "
                     f"({100*blk['ha_ancore']/ha:.0f}% del blocco)")
    else:
        rischi.append('nessuna terra gia' + "'" + ' controllata: nessun ancoraggio, '
                      'il progetto dipende al 100% da terzi')

    if d_se_m is not None:
        km = d_se_m / 1000.0
        costo = (round(km * 100_000), round(km * 150_000))
        if km > 5:
            rischi.append(f'connessione a {km:.1f} km: sopra la soglia economica dei 5 km '
                          f'(cavidotto stimato {costo[0]:,}-{costo[1]:,} EUR)'.replace(',', '.'))
        else:
            punti.append(f'connessione a {km:.1f} km (cavidotto stimato '
                         f'{costo[0]:,}-{costo[1]:,} EUR)'.replace(',', '.'))

    # frammentazione interna: quante isole se si stringe la soglia di contiguita'
    isole = None
    if adj is not None and A is not None:
        idx = {(p['fg'], p['pla']) for p in part}
        P = A['ammesse'] if isinstance(A, dict) else A
        sel = {i for i, p in enumerate(P) if (p['fg'], p['pla']) in idx}
        vis, isole = set(), 0
        for s in sel:
            if s in vis:
                continue
            isole += 1
            pila = [s]
            while pila:
                x = pila.pop()
                if x in vis:
                    continue
                vis.add(x)
                pila.extend((adj[x] & sel) - vis)
        if isole > 1:
            rischi.append(f'il blocco e\' in {isole} tronconi separati, non uno solo')

    # La potenza si stima sulla superficie INSTALLABILE, non su quella netta: un
    # blocco contiguo puo' essere una catena serpeggiante in cui meta' degli
    # ettari sono code troppo strette per ospitare una fila di moduli.
    ha_inst, resa = None, None
    try:
        from . import installabile as INST
        r_inst = INST.analizza(part)
        ha_inst, resa = r_inst['ha_installabile'], r_inst['resa_forma']
        if resa < 0.65:
            rischi.append(f'forma sfavorevole: solo {ha_inst} ha installabili su {ha} netti '
                          f'({100*resa:.0f}%) — il blocco e\' una catena, non un campo')
        else:
            punti.append(f'forma compatta: {ha_inst} ha installabili ({100*resa:.0f}% del netto)')
    except Exception as e:
        rischi.append(f'superficie installabile NON verificata ({type(e).__name__})')

    base = ha_inst if ha_inst is not None else ha
    mwp = (round(base * mwp_per_ha[0], 1), round(base * mwp_per_ha[1], 1))
    return {'ha_netti': ha, 'ha_installabile': ha_inst, 'resa_forma': resa,
            'ha_lordi': blk['ha_lordi'], 'n_particelle': blk['n'],
            'n_acquisti': n_acq, 'ha_acquisti': round(ha_acq, 2),
            'ha_per_controparte': round(ha_acq / n_acq, 2) if n_acq else None,
            'particelle_per_80pct': n80, 'quota_max_singola_pct': quota_max,
            'isole': isole, 'mwp_stimati': mwp, 'punti_forti': punti, 'rischi': rischi,
            'nota_controparti': ('conteggio per PARTICELLA, non per proprietario: '
                                 'senza visure il numero reale di controparti puo\' solo '
                                 'essere MINORE (piu\' particelle allo stesso intestatario). '
                                 'E\' un limite superiore.')}


def print_bancabilita(b):
    print(f"\n=== BANCABILITA' ===")
    print(f"  {b['ha_netti']} ha netti su {b['ha_lordi']} catastali · {b['n_particelle']} particelle")
    if b.get('ha_installabile') is not None:
        print(f"  ha INSTALLABILI: {b['ha_installabile']} (resa di forma {100*b['resa_forma']:.0f}%)")
    print(f"  potenza stimata (agriPV avanzato): {b['mwp_stimati'][0]}-{b['mwp_stimati'][1]} MWp"
          + ('  [sugli ha installabili]' if b.get('ha_installabile') is not None else ''))
    print(f"  da acquisire: {b['n_acquisti']} particelle / {b['ha_acquisti']} ha")
    for p in b['punti_forti']:
        print(f"  + {p}")
    for r in b['rischi']:
        print(f"  ! {r}")
    print(f"  ~ {b['nota_controparti']}")


# ---------------------------------------------------------------- 5. export
_HTML = r"""<!DOCTYPE html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITOLO__</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#map{height:100%;margin:0}.panel{position:absolute;top:10px;right:10px;z-index:1000;background:rgba(255,255,255,.96);padding:11px 13px;border-radius:8px;font:13px system-ui;max-width:300px;box-shadow:0 1px 8px rgba(0,0,0,.4)}.panel h3{margin:0 0 7px;font-size:14px}.row{display:flex;align-items:center;gap:6px;margin:3px 0}.sw{width:15px;height:11px;display:inline-block;border:1px solid #111}</style>
</head><body><div id="map"></div>
<div class="panel"><h3>__TITOLO__</h3>
<div class="row"><span class="sw" style="background:#1a8a3a"></span> Gi&agrave; controllata</div>
<div class="row"><span class="sw" style="background:#ff8a3c"></span> Da acquisire &ge;1 ha netto</div>
<div class="row"><span class="sw" style="background:#ffd27f"></span> Da acquisire &lt;1 ha netto</div>
<div style="margin-top:8px;font-size:12px" id="stat"></div>
<div style="margin-top:6px;font-size:11px;color:#555">__NOTA__</div></div>
<script>
var DATA=__J__;var map=L.map('map');
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:20,attribution:'Esri'}).addTo(map);
var b=[];
DATA.forEach(function(f){
 L.polygon(f.poly,{color:f.anc?'#0d5c22':'#a05000',weight:f.anc?2:1,fillColor:f.fc,fillOpacity:.62}).addTo(map)
  .bindPopup('<b>Fg '+f.fg+'/'+f.pla+'</b><br>catastali '+f.ha+' ha<br><b>utili '+f.netti+' ha</b>'+(f.det?'<br><i>'+f.det+'</i>':'')+'<br>'+(f.anc?'GIA CONTROLLATA':'da acquisire'));
 f.poly.forEach(p=>b.push(p));
});
map.fitBounds(b,{padding:[25,25]});
document.getElementById('stat').innerHTML='<b>'+DATA.length+' particelle = __TOT__ ha utili</b><br>(__LORDI__ ha catastali)<br>gi&agrave; tue __F__ ha &middot; da acquisire __A__ ha (__NA__ part.)';
</script></body></html>"""

NOTA_METODO = ('Filtri applicati <b>a monte</b> della crescita: nessun fabbricato catastale '
               '(WMS AdE), bosco art.142-g e fasce lago/fiume sotto soglia, no usi civici / '
               'art.136 / archeologia, no habitat 6210-6220. Superficie al <b>NETTO</b> di '
               'bosco, fasce e sedime.')


def esporta_mappa(blk, out_html, nota=NOTA_METODO):
    D = []
    for p in blk['particelle']:
        det = ' · '.join(f'{k.replace("_pct","")} {v:.0f}%'
                         for k, v in (p.get('detrazioni') or {}).items() if v >= 1)
        D.append({'poly': p['poly'], 'fg': p['fg'], 'pla': p['pla'],
                  'ha': round(p['ha'], 2), 'netti': round(p['netti'], 2),
                  'anc': p['ancora'], 'det': ('-' + det) if det else '',
                  'fc': '#1a8a3a' if p['ancora'] else ('#ff8a3c' if p['netti'] >= 1 else '#ffd27f')})
    h = (_HTML.replace('__J__', json.dumps(D))
         .replace('__TITOLO__', blk['titolo']).replace('__NOTA__', nota)
         .replace('__TOT__', f"{blk['ha_netti']:.1f}").replace('__LORDI__', f"{blk['ha_lordi']:.1f}")
         .replace('__F__', f"{blk['ha_ancore']:.2f}").replace('__A__', f"{blk['ha_acquisti']:.1f}")
         .replace('__NA__', str(blk['n_acquisti'])))
    os.makedirs(os.path.dirname(os.path.abspath(out_html)), exist_ok=True)
    open(out_html, 'w', encoding='utf-8').write(h)
    return out_html


def esporta_visure(blk, out_csv, comune=''):
    """Lista di lavoro per le visure, ordinata per ettari.

    Il numero di proprietari non e' pubblico: questa non e' una risposta, e' la
    domanda messa in fila in modo che una sessione sola copra il grosso.
    """
    acq = [p for p in blk['particelle'] if not p['ancora']]
    tot = sum(p['netti'] for p in acq) or 1
    os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
    with open(out_csv, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['priorita', 'comune', 'foglio', 'particella', 'ha_catastali',
                    'ha_utili', 'quota_cum_%', 'intestatario_DA_COMPILARE', 'note'])
        cum = 0
        for i, p in enumerate(acq, 1):
            cum += p['netti']
            w.writerow([i, comune, p['fg'], p['pla'],
                        f"{p['ha']:.3f}".replace('.', ','),
                        f"{p['netti']:.3f}".replace('.', ','),
                        f'{100*cum/tot:.0f}', '', ''])
    return out_csv


def geometrie_mancanti(blk):
    """Particelle senza poligono, in forma `fg/pla`."""
    return [f"{p.get('fg')}/{p.get('pla')}" for p in (blk.get('particelle') or [])
            if not (p.get('poly') or p.get('anello') or p.get('ring'))]


def controlla_geometrie(blk, b=None, verbose=True):
    """Le geometrie sono l'unico dato del blocco che NON si puo' ricostruire a mano.

    Ettari e intestatari si ricopiano da una visura; il perimetro no: senza quello
    il blocco non si vede sul satellite, non si apre in QGIS, non si riesporta.
    Il 26/07/2026 un blocco e' stato salvato da uno script che filtrava via `poly`
    per alleggerire il json, e l'unica copia superstite delle geometrie e' finita
    per caso dentro l'HTML della mappa. Da allora la perdita si dichiara subito.
    """
    mancanti = geometrie_mancanti(blk)
    if mancanti:
        msg = (f'{len(mancanti)} particelle SENZA geometria '
               f"({', '.join(mancanti[:5])}{'...' if len(mancanti) > 5 else ''}): "
               f'il blocco non e verificabile a vista ne riesportabile')
        if b is not None:
            b.setdefault('rischi', []).append(msg)
        if verbose:
            print(f'   ATTENZIONE: {msg}')
    return mancanti


def salva_json(blk, path, **extra):
    """L'unico modo sanzionato di mettere un blocco su disco.

    Esiste per una ragione sola: impedire che un chiamante rifaccia a mano il
    `json.dump` e nel farlo tolga `poly`. Le geometrie non si sacrificano per
    alleggerire il file — pesano poche decine di KB e sono l'unica cosa che il
    tool non sa rigenerare identica il giorno dopo, perche' il catasto cambia.
    """
    mancanti = geometrie_mancanti(blk)
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    payload = dict(extra)
    payload['blocco'] = blk
    payload['particelle_senza_geometria'] = mancanti or None
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return path, mancanti


def esporta(blk, out_dir, comune='', satellite=True, A=None, fr=None, b=None,
            visure_dir=None, prov=None, coda_export=None, verbose=True):
    """L'UNICO posto che decide cosa produce il tool.

    Sta qui, e non duplicato fra `pipeline()` e la CLI, perche' finche' erano due
    la CLI e' rimasta indietro: mappa e visure si', screening satellitare no. Un
    output che dipende da quale porta si entra e' un output che si dimentica.

    Produce sempre: mappa · lista visure · forma del blocco · **fogli-contatti
    satellitari** · json riepilogativo.
    """
    file, r_inst = {}, None
    if not out_dir:
        return file, r_inst
    os.makedirs(out_dir, exist_ok=True)
    # per primo, prima di qualunque output: se le geometrie non ci sono, meta'
    # di cio' che segue e' muto (satellite, forma, geojson) e va detto ORA.
    controlla_geometrie(blk, b=b, verbose=verbose)
    # cio' che arricchisci() non ha potuto controllare e' un rischio del blocco
    # come gli altri: se resta dentro ad A non lo legge nessuno.
    if b is not None and A:
        b.setdefault('rischi', []).extend(A.get('non_verificati') or [])
        b.setdefault('rischi', []).extend(A.get('segnalazioni') or [])
    file['mappa'] = esporta_mappa(blk, os.path.join(out_dir, 'blocco.html'))
    file['visure'] = esporta_visure(blk, os.path.join(out_dir, 'visure.csv'), comune=comune)

    # geometrie fuori dal tool: e' l'unico output che permette di sovrapporre i
    # livelli UFFICIALI (SITAP, PAI, ZPS, catasto) alle particelle e vedere se la
    # risposta del codice torna. I bug trovati finora sono stati trovati a vista.
    try:
        from . import gis as GIS
        file['geojson'], scartate = GIS.esporta_geojson(
            blk, os.path.join(out_dir, 'blocco.geojson'), comune=comune)
        # le geometrie del tutto assenti le ha gia' dichiarate controlla_geometrie:
        # qui resta il caso peggiore da diagnosticare, il poligono che c'e' ma e'
        # degenere (meno di 3 vertici) e passerebbe per buono a un controllo di
        # sola presenza.
        degeneri = [x for x in scartate if x not in geometrie_mancanti(blk)]
        if degeneri:
            msg = (f"{len(degeneri)} particelle con geometria DEGENERE "
                   f"({', '.join(degeneri[:5])}{'...' if len(degeneri) > 5 else ''}): "
                   f"il poligono esiste ma ha meno di 3 vertici, escluse dal GeoJSON")
            if b is not None:
                b.setdefault('rischi', []).append(msg)
            if verbose:
                print(f'   ATTENZIONE: {msg}')
    except Exception as e:
        if b is not None:
            b.setdefault('rischi', []).append(
                f'export GeoJSON NON riuscito ({type(e).__name__}): il blocco non '
                f'e verificabile su QGIS o geojson.io')
        if verbose:
            print(f'   ATTENZIONE: export GeoJSON fallito ({e})')

    # viabilita': la sede stradale non e' installabile e una carraia che attraversa
    # SPEZZA il campo. Va tolta dalla maschera prima dell'erosione, non dopo.
    S = None
    try:
        from . import strade as ST
        lats = [q[0] for p in blk['particelle'] for q in p['poly']]
        lons = [q[1] for p in blk['particelle'] for q in p['poly']]
        S = ST.scarica((min(lats) - 0.002, min(lons) - 0.002,
                        max(lats) + 0.002, max(lons) + 0.002))
        r_str = ST.occupazione(blk['particelle'], S)
        if verbose:
            ST.print_occupazione(r_str)
        if b is not None and r_str['n_con_strada']:
            b.setdefault('rischi', []).append(
                f"{r_str['n_con_strada']} particelle attraversate da viabilita "
                f"(>=5% di sede stradale): verificare accessi e fasce di rispetto "
                f"con l'ente gestore")
    except Exception as e:
        r_str = None
        if b is not None:
            b.setdefault('rischi', []).append(
                f'viabilita NON verificata ({type(e).__name__}): la sede stradale '
                f'potrebbe essere conteggiata fra gli ettari utili')
        if verbose:
            print(f'   ATTENZIONE: viabilita non verificata ({e})')

    try:
        from . import installabile as INST
        r_inst = INST.analizza(blk['particelle'], strade=S)
        file['forma'] = INST.png(blk['particelle'], os.path.join(out_dir, 'forma.png'))
        if verbose:
            INST.print_analisi(r_inst)
    except Exception as e:
        if verbose:
            print(f'   forma non calcolata: {type(e).__name__}')
    if satellite:
        try:
            file.update(_screening_satellitare(blk, out_dir, r_inst, verbose))
        except Exception as e:
            # mai silenzioso: un controllo saltato va detto, non nascosto
            if b is not None:
                b.setdefault('rischi', []).append(
                    f'screening satellitare NON eseguito ({type(e).__name__}): '
                    f"l'occupazione reale del suolo resta NON verificata")
            if verbose:
                print(f'   ATTENZIONE: screening satellitare fallito ({e})')

        # ISPEZIONE: leggere le immagini, non solo produrle. Il foglio-contatti
        # sopra e' un output che qualcuno DEVE guardare, e "qualcuno lo guardera'"
        # non e' un controllo — e' una speranza. `ispezione` confronta l'immagine
        # coi layer e restituisce la coda ordinata di cio' che non torna, con i
        # ritagli accanto. Fino al 12/08/2026 il modulo esisteva e non veniva mai
        # chiamato dalla pipeline: andava lanciato a mano, cioe' solo dopo che il
        # problema era gia' saltato fuori in altro modo.
        try:
            from . import ispezione as ISP
            ISPR = ISP.controlla(blk['particelle'],
                                 chioma={_id(p): {'pct': p['chioma_pct']}
                                         for p in blk['particelle']
                                         if p.get('chioma_pct') is not None},
                                 colture={_id(p): p.get('coltura')
                                          for p in blk['particelle'] if p.get('coltura')},
                                 verbose=False)
            d_isp = os.path.join(out_dir, 'ispezione')
            ISP.esporta_ritagli(blk['particelle'], ISPR, d_isp)
            file['ispezione'] = d_isp
            if verbose:
                print(ISP.print_report(ISPR, top=8))
            if b is not None:
                b.setdefault('rischi', []).extend(ISP.rischi(ISPR))
        except Exception as e:
            if b is not None:
                b.setdefault('rischi', []).append(
                    f'ispezione delle immagini NON eseguita ({type(e).__name__}): '
                    f'le foto ci sono ma nessuno le ha lette')
            if verbose:
                print(f'   ATTENZIONE: ispezione immagini fallita ({e})')

    # visure: se ci sono, il conteggio passa da PARTICELLE a PROPRIETARI.
    # E' l'unico modo di sapere davvero con quante persone si tratta.
    C = None
    if visure_dir and os.path.isdir(visure_dir):
        try:
            from . import visure as VIS
            V = VIS.leggi_cartella(visure_dir)
            C = VIS.aggrega(V, blocco=blk)
            if verbose:
                VIS.print_controparti(C)
            if b is not None:
                b.update(VIS.applica_a_bancabilita(b, C))
            # sapere CON CHI si tratta non basta: serve sapere quando quella firma
            # puo' materialmente arrivare. Un fondo perfetto con la successione non
            # aperta non si compra lo stesso.
            from . import titoli as TT
            TIT = TT.analizza(C)
            if verbose and TIT['n']:
                print(TT.print_prerequisiti(TIT))
            if b is not None:
                b.setdefault('rischi', []).extend(TT.rischi(TIT))
            file['controparti'] = os.path.join(out_dir, 'controparti.json')
            json.dump({k: v for k, v in C.items() if k != 'controparti'} |
                      {'controparti': [{kk: vv for kk, vv in x.items() if kk != 'dettaglio'}
                                       for x in C['controparti']]},
                      open(file['controparti'], 'w', encoding='utf-8'),
                      indent=1, ensure_ascii=False)
        except Exception as e:
            if verbose:
                print(f'   visure non lette ({type(e).__name__}: {e})')
    elif b is not None:
        # Senza visure il conteggio per particella e' il limite SUPERIORE. Dare solo
        # quello fa sembrare il blocco piu' difficile di quanto sia: 89 particelle
        # possono essere di pochi proprietari. La numerazione catastale porta il
        # limite inferiore — e una forbice dichiarata vale piu' di un estremo solo.
        nota = ('quadro proprietario SCONOSCIUTO: nessuna visura caricata, '
                'le controparti sono contate per particella (limite superiore)')
        try:
            from . import frazionamento as FZ
            s = FZ.stima([p for p in blk['particelle'] if not p.get('ancora')])
            if s['particelle_da_acquisire']:
                nota = (f"quadro proprietario SCONOSCIUTO (nessuna visura): le controparti "
                        f"da acquisire stanno fra {s['controparti_min_stimate']} e "
                        f"{s['controparti_max']} — il minimo e' una STIMA dalla numerazione "
                        f"catastale, solo le visure fissano il numero vero")
                if verbose:
                    FZ.print_stima(s)
        except Exception as e:
            if verbose:
                print(f'   stima frazionamento non riuscita ({type(e).__name__})')
        b.setdefault('rischi', []).append(nota)

    # capacita' di rete: e' il gate che puo' azzerare tutto il resto, quindi
    # entra nel riepilogo come gli altri rischi e non come nota a margine.
    cap = None
    if prov:
        try:
            from . import capacita as CAP
            # `prov` puo' arrivare come sigla (da pipeline, che la usa per i layer
            # regionali) o come nome esteso (dalla CLI --prov-nome). Il servizio
            # e-Distribuzione vuole il nome o il codice: la traduzione sta qui,
            # una volta sola, invece di obbligare il chiamante a saperlo. Era
            # esattamente il motivo per cui pipeline() non passava affatto `prov`
            # e il gate di rete non girava mai (audit 08/08/2026).
            c = CAP.criticita_provincia(config.nome_prov(prov),
                                        cod_pro=config.cod_prov(prov))
            q = (CAP.coda_da_export(coda_export, prov=config.nome_prov(prov))
                 if coda_export and os.path.exists(coda_export) else None)
            mwp = (b or {}).get('mwp_stimati')
            cap = CAP.valuta(c, q, mwp=(mwp[1] if mwp else None))
            if verbose:
                CAP.print_valutazione(cap)
            if b is not None:
                b.setdefault('rischi', []).extend(cap['rischi'])
                b.setdefault('punti_forti', []).extend(cap['punti_forti'])
                b['rete_da_verificare'] = cap['da_verificare']
        except Exception as e:
            if b is not None:
                b.setdefault('rischi', []).append(
                    f'capacita di rete NON verificata ({type(e).__name__}): '
                    f'e il gate che puo azzerare il progetto')
            if verbose:
                print(f'   ATTENZIONE: capacita di rete non verificata ({e})')
    elif b is not None:
        b.setdefault('rischi', []).append(
            'capacita di rete NON verificata: passare --prov per interrogare '
            'le aree critiche e-Distribuzione')

    # chi decide e dove si presenta l'istanza. Sembra segreteria e non lo e':
    # a Morcone la VINCA la rilascia il Comune (delega regionale) e l'AU va al
    # S.U.D. ZES, non al SUAP. Chi prepara il dossier per lo sportello sbagliato
    # se ne accorge al protocollo, settimane dopo.
    if comune:
        try:
            from . import enti as EN
            E = EN.competenze(comune, config.sigla_prov(prov) if prov else None)
            if verbose and E['registrato']:
                print(EN.print_competenze(E))
            if b is not None:
                b.setdefault('rischi', []).extend(EN.rischi(E))
        except Exception as e:
            if verbose:
                print(f'   enti competenti non letti ({type(e).__name__})')

        # e come e' andata a chi ci ha provato prima, qui. Un layer dice cosa e'
        # vietato in astratto; le VINCA gia' decise nello stesso comune dicono
        # cosa passa davvero, con quali prescrizioni e chi firma — e se un
        # intervento simile e' gia' stato rigettato, quello vale piu' di
        # qualunque punteggio.
        try:
            from . import precedenti as PR
            PRE = PR.contro_blocco(blk, comune, config.sigla_prov(prov) if prov else None,
                                   tipo='fer')
            if verbose and (PRE['letto'] or PRE['avvisi']):
                print(PR.print_precedenti(PRE))
            if b is not None:
                b.setdefault('rischi', []).extend(PR.rischi(PRE))
        except Exception as e:
            if verbose:
                print(f'   precedenti VINCA non letti ({type(e).__name__})')

    # piano di offerta: e' la domanda successiva a "quanto vale il blocco" —
    # a QUESTA persona, quanto offro. Sta qui e non a parte perche' senza il
    # numero da mettere sul tavolo il blocco resta un esercizio cartografico:
    # senza visure il piano esce per particella e lo dichiara.
    P = None
    try:
        from . import prezzo as PZ
        P = PZ.piano(blk, controparti=C, prov=(config.sigla_prov(prov) or 'BN'),
                     mwp=((b or {}).get('mwp_stimati') or [None, None])[1],
                     ha_installabili=(r_inst or {}).get('ha_installabile'),
                     criticita=((cap or {}).get('criticita') or {}).get('livello'))
        if verbose:
            PZ.print_piano(P)
        if b is not None:
            b.setdefault('rischi', []).extend(P['avvisi'])
    except Exception as e:
        if b is not None:
            b.setdefault('rischi', []).append(
                f'piano di offerta NON calcolato ({type(e).__name__}): resta da stabilire '
                f'quanto offrire e a chi')
        if verbose:
            print(f'   piano di offerta non calcolato ({e})')

    # DECISIONE: l'ultima cosa, perche' legge tutto quello che gli altri hanno
    # scritto in `b['rischi']`. Sette righe di rischio tutte sullo stesso piano
    # lasciano al lettore il lavoro di capire quale puo' chiudere la partita:
    # qui vengono ordinate per valore dell'informazione — prima cio' che costa
    # poco e puo' azzerare il progetto.
    # ⚠️ NON subordinata alla bancabilita': un blocco esportato senza bancabilita'
    # e' proprio quello che ha piu' bisogno dell'elenco delle domande, perche' non
    # ne ha ancora nessuna risposta.
    if True:
        try:
            from . import decisione as DEC
            st, note = DEC.da_rischi((b or {}).get('rischi') or [])
            DE = DEC.valuta(st, comune=comune, prov=(prov or ''), note=note)
            file['decisione'] = os.path.join(out_dir, 'decisione.txt')
            with open(file['decisione'], 'w', encoding='utf-8') as f:
                testo = DEC.print_decisione(DE)
                mossa = DEC.prossima_mossa(DE) or 'nessuna verifica aperta'
                f.write(testo + os.linesep * 2 + 'PROSSIMA MOSSA: ' + mossa + os.linesep)
            if b is not None:
                b['decisione'] = {'giudizio': DE['giudizio'], 'perche': DE['perche'],
                                  'ore_killer': DE['ore_per_chiudere_i_killer'],
                                  'prossima_mossa': mossa}
            if verbose:
                print(DEC.print_decisione(DE, top=5))
        except Exception as e:
            if verbose:
                print(f'   decisione non calcolata ({type(e).__name__}: {e})')

    # il riepilogo va stampato ORA, non prima: viabilita', forma e satellite
    # aggiungono rischi a `b`, e una bancabilita' stampata a meta' raccolta e'
    # una bancabilita' che nasconde proprio cio' che si e' appena scoperto.
    if verbose and b is not None:
        print_bancabilita(b)

    file['json'] = os.path.join(out_dir, 'blocco.json')
    json.dump({'comune': comune, 'prov': prov,
               'ammissibilita': ({k: v for k, v in A.items() if k != 'ammesse'} if A else None),
               'frontiera': fr, 'blocco': blk, 'bancabilita': b,
               'viabilita': r_str,
               'controparti': ({k: v for k, v in C.items() if k != 'controparti'} if C else None),
               'capacita_rete': cap,
               'prezzo': P,
               'installabile': ({k: v for k, v in r_inst.items() if k != 'particelle'}
                                if r_inst else None)},
              open(file['json'], 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    # la pagina che si manda al developer. Sta qui e non a parte per la stessa
    # ragione del satellite (Fase 34): un output che va richiesto e' un output
    # che si dimentica — e questo e' l'unico che esce dallo studio.
    try:
        from datetime import date
        from . import teaser as TS
        # si passa il PATH, non il dict: cosi' teaser trova da solo le immagini
        # gia' prodotte accanto (forma, satellite) e le referenzia in relativo.
        file['teaser'], _t = TS.genera(file['json'],
                                       os.path.join(out_dir, 'teaser.html'),
                                       data=date.today().strftime('%d/%m/%Y'))
    except Exception as e:
        if verbose:
            print(f'   teaser non generato ({type(e).__name__}: {e})')

    if verbose:
        print('\nscritti:\n  ' + '\n  '.join(str(v) for v in file.values()))
    return file, r_inst


# ---------------------------------------------------------------- pipeline
def _screening_satellitare(blk, out_dir, r_inst=None, verbose=True):
    """Fogli-contatti satellitari del blocco. NON e' un extra: e' un controllo.

    Sul blocco EDP elimino' 3 ancore su 15 (una "voto 10" era la sottostazione
    stessa); su Morcone ha rivelato che Fg82/117 — 2,35 ha "utili", seconda
    particella del blocco — e' un nastro lungo un torrente. Catasto e vincoli
    dicono cosa la particella *e' sulla carta*; solo l'immagine dice cosa c'e'
    davvero sopra. Per questo il tool lo produce sempre, senza che si debba
    chiedere: un output che va richiesto e' un output che si dimentica.

    Due fogli separati — cio' che e' gia' tuo e cio' che devi comprare — perche'
    si guardano con domande diverse.
    """
    from . import satcheck as SC

    quota = {}
    if r_inst:
        quota = {(q['fg'], q['pla']): q for q in r_inst['particelle']}

    def _sel(ancora):
        out = {}
        for p in blk['particelle']:
            if bool(p.get('ancora')) is not ancora:
                continue
            d = p.get('detrazioni') or {}
            n = []
            if (d.get('edificato_pct') or 0) >= 1:
                n.append(f"ed{d['edificato_pct']:.0f}%")
            if (d.get('bosco_pct') or 0) >= 1:
                n.append(f"bo{d['bosco_pct']:.0f}%")
            q = quota.get((p['fg'], p['pla']))
            if q:
                n.append(f"inst{100*q['quota_installabile']:.0f}%")
            out[f"{p['fg']}-{p['pla']}"] = {'anello': p['poly'], 'ha': p['netti'],
                                            'nota': ' '.join(n)}
        return out

    file = {}
    for ancora, nome in ((False, 'da_acquisire'), (True, 'gia_tue')):
        sel = _sel(ancora)
        if not sel:
            continue
        d = os.path.join(out_dir, 'satellite_' + nome)
        if verbose:
            print(f'   satellite {nome}: {len(sel)} particelle…')
        SC.render_block(sel, d, z=18)
        file['satellite_' + nome] = os.path.join(d, '_contact_sheet.png')
    return file


def pipeline(parcels, prov, ancore_ids=(), target_ha=30.0, tech='agriPV',
             d_se_m=None, comune='', out_dir=None, targets=(15, 20, 25, 30, 35),
             satellite=True, verbose=True, visure_dir=None, coda_export=None,
             arricchimento=True):
    """Da un elenco di particelle col poligono al blocco bancabile, in una chiamata.

    Misura i vincoli e i fabbricati *sui poligoni* (mai sui centroidi: il
    centroide non e' un'approssimazione, e' una risposta binaria a una domanda
    continua), poi ammette, cresce e valuta.

    Restituisce {'ammissibilita','frontiera','blocco','bancabilita','file'}.
    Richiede rete: vincoli.feasibility e occupazione interrogano WFS/WMS pubblici.

    ⚠ Fino all'08/08/2026 questa funzione riceveva `prov` e NON lo passava a
    `esporta()`: chi entrava di qui perdeva il gate di rete, le controparti dalle
    visure e la coda, senza nemmeno una riga nei rischi. E' la malattia della
    Fase 34 — un output (qui: un controllo) che dipende da quale porta si entra —
    e la cura e' la stessa: un solo posto che decide, chiamato da entrambe.
    """
    from . import vincoli as VN
    from . import occupazione as OC

    # Ogni modulo a monte vuole i suoi nomi: vincoli.feasibility chiave su
    # p['id'] e legge 'anello', occupazione lavora su un dict {id: ...}. Qui si
    # traduce una volta sola, invece di far combaciare i formati a mano ogni volta.
    for p in parcels:
        p.setdefault('id', _id(p))
        p.setdefault('anello', p['poly'])
    d_parcels = {}
    for p in parcels:
        ring = p['poly']
        d_parcels[_id(p)] = {
            'anello': ring, 'ha': p.get('ha') or 0,
            # il centroide serve solo a vincoli.py per scegliere i layer regionali:
            # la MISURA resta sul poligono ('anello'), mai sul punto.
            'lat': p.get('lat', sum(q[0] for q in ring) / len(ring)),
            'lon': p.get('lon', sum(q[1] for q in ring) / len(ring)),
        }

    if verbose:
        print(f'1/5 vincoli su {len(parcels)} particelle (sui POLIGONI)…')
    vinc = VN.feasibility(d_parcels, prov)

    if verbose:
        print('2/5 fabbricati (WMS AdE, screening a due stadi)…')
    lats = [q[0] for p in parcels for q in p['poly']]
    lons = [q[1] for p in parcels for q in p['poly']]
    m = 0.0008   # margine: un fabbricato a cavallo del bordo deve restare nel mosaico
    mos = OC.Mosaico((min(lats) - m, min(lons) - m, max(lats) + m, max(lons) + m),
                     verbose=verbose)
    occ = OC.screening_due_stadi(d_parcels, mos, verbose=verbose)

    if verbose:
        print('3/6 ammissibilita…')
    A = ammissibilita(parcels, vinc, occ, tech=tech)

    if arricchimento:
        if verbose:
            print('4/6 chioma, colture, prossimita, crinali (PRIMA della crescita)…')
        A = arricchisci(A, prov=prov, visure_dir=visure_dir, verbose=verbose)
    if verbose:
        print_ammissibilita(A)

    anc = set(ancore_ids)
    ancore = [i for i, p in enumerate(A['ammesse']) if _id(p) in anc] or None
    if verbose:
        print('5/6 adiacenza e frontiera…')
    adj = adiacenza(A)
    fr = frontiera(A, adj, targets=targets, ancore=ancore)
    if verbose:
        print_frontiera(fr)

    if verbose:
        print('6/6 crescita del blocco…')
    blk = cresci_migliore(A, adj, target_ha, ancore=ancore,
                          obiettivo='ancore' if ancore else 'controparti')
    if blk is None:
        if verbose:
            print(f'nessun blocco contiguo raggiunge {target_ha} ha netti.')
        return {'ammissibilita': A, 'frontiera': fr, 'blocco': None,
                'bancabilita': None, 'file': {}}

    b = bancabilita(blk, d_se_m=d_se_m, adj=adj, A=A)
    if verbose:
        print(f"\n{blk['titolo']}")
        # il riepilogo lo stampa esporta(), a raccolta rischi completata

    file, r_inst = esporta(blk, out_dir, comune=comune, satellite=satellite,
                           A=A, fr=fr, b=b, visure_dir=visure_dir, prov=prov,
                           coda_export=coda_export, verbose=verbose)
    return {'ammissibilita': A, 'frontiera': fr, 'blocco': blk, 'bancabilita': b,
            'installabile': r_inst, 'file': file}


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description='Costruisce il blocco contiguo bancabile.')
    ap.add_argument('--parcels', help="JSON [{'fg','pla','ha','poly'}]")
    ap.add_argument('--from-scan', dest='from_scan', default=None,
                    help="esito di scan.py: filtra, traduce e fa girare l'intera "
                         'pipeline (vincoli e fabbricati rimisurati sui poligoni). '
                         'E l alternativa a --parcels/--vincoli/--occupazione')
    ap.add_argument('--voto-min', type=float, default=None,
                    help='con --from-scan: soglia sul voto 0-10 dello scan')
    ap.add_argument('--vincoli', help='JSON output di vincoli.feasibility')
    ap.add_argument('--occupazione', help='JSON output di occupazione.screening_due_stadi')
    ap.add_argument('--ancore', default=None, help='JSON ["fg_pla",...] terra gia\' controllata')
    ap.add_argument('--target', type=float, default=30.0)
    ap.add_argument('--d-se-m', type=float, default=None)
    ap.add_argument('--comune', default='')
    ap.add_argument('--out-dir', default='.')
    ap.add_argument('--prov', '--prov-nome', dest='prov', default=None,
                    help='provincia: sigla (BN) o nome (Benevento). Serve alla criticita '
                         'di rete e-Distribuzione e alla fascia crinali del PTCP')
    ap.add_argument('--no-arricchimento', action='store_true',
                    help='salta chioma, colture, prossimita e crinali (di default girano '
                         'SEMPRE, prima della crescita: sono controlli che tolgono ettari, '
                         'non extra da chiedere)')
    ap.add_argument('--coda', default=None,
                    help='export Terna Econnextion (xlsx/csv) per la coda di connessione')
    ap.add_argument('--visure', default=None,
                    help='cartella con le visure PDF gia scaricate dalla tua area riservata: '
                         'il conteggio delle controparti passa da particelle a PROPRIETARI')
    ap.add_argument('--no-satellite', action='store_true',
                    help='salta i fogli-contatti satellitari (di default vengono SEMPRE prodotti: '
                         'catasto e vincoli dicono cosa la particella e sulla carta, '
                         'solo l immagine dice cosa c e davvero sopra)')
    A_ = ap.parse_args()
    anc_ids = set(json.load(open(A_.ancore, encoding='utf-8'))) if A_.ancore else set()

    # --- il ponte: dallo scan al blocco in un comando solo ---
    if A_.from_scan:
        d = da_scan(A_.from_scan, voto_min=A_.voto_min)
        print(f"dallo scan: {d['n_in']} particelle -> {d['n_out']} candidate")
        for k, n in sorted(d['scartate'].items(), key=lambda x: -x[1]):
            print(f'   scartate {k:<28s} {n:5d}')
        if not d['parcels']:
            raise SystemExit('nessuna particella supera i filtri: allargare --voto-min')
        r = pipeline(d['parcels'], A_.prov, ancore_ids=anc_ids, target_ha=A_.target,
                     d_se_m=A_.d_se_m, comune=A_.comune, out_dir=A_.out_dir,
                     satellite=not A_.no_satellite, visure_dir=A_.visure,
                     coda_export=A_.coda, arricchimento=not A_.no_arricchimento)
        return r

    if not (A_.parcels and A_.vincoli and A_.occupazione):
        raise SystemExit('servono --parcels + --vincoli + --occupazione, '
                         'oppure --from-scan che li ricava da solo')
    parcels = json.load(open(A_.parcels, encoding='utf-8'))
    vinc = json.load(open(A_.vincoli, encoding='utf-8'))
    occ = json.load(open(A_.occupazione, encoding='utf-8'))

    A = ammissibilita(parcels, vinc, occ)
    # gli stessi controlli della pipeline, chiamati dallo stesso posto: se questa
    # riga sparisce, la CLI torna a produrre blocchi con dentro il bosco vero.
    if not A_.no_arricchimento:
        A = arricchisci(A, prov=A_.prov, visure_dir=A_.visure)
    print_ammissibilita(A)
    ancore = [i for i, p in enumerate(A['ammesse']) if _id(p) in anc_ids]
    print(f"\nancore (terra gia' controllata) ammesse: {len(ancore)} particelle, "
          f"{sum(A['ammesse'][i]['netti'] for i in ancore):.2f} ha netti")

    adj = adiacenza(A)
    comp = componenti(A, adj)
    print(f"blocchi contigui: {len(comp)} | il maggiore: {len(comp[0])} part. "
          f"{sum(A['ammesse'][i]['netti'] for i in comp[0]):.1f} ha netti")

    print('\n=== FRONTIERA ettari <-> controparti ===')
    fr = frontiera(A, adj, ancore=ancore or None)
    print_frontiera(fr)

    blk = cresci_migliore(A, adj, A_.target, ancore=ancore or None,
                          obiettivo='ancore' if ancore else 'controparti')
    if not blk:
        print(f"\nnessun blocco contiguo raggiunge {A_.target} ha netti.")
        return
    print(f"\n{blk['titolo']}")
    print(f"  gia' tue {blk['ha_ancore']} ha ({blk['n_ancore']} part.) | "
          f"da acquisire {blk['ha_acquisti']} ha ({blk['n_acquisti']} part.)")
    b = bancabilita(blk, d_se_m=A_.d_se_m, adj=adj, A=A)
    esporta(blk, A_.out_dir, comune=A_.comune, satellite=not A_.no_satellite,
            A=A, fr=fr, b=b, visure_dir=A_.visure,
            prov=A_.prov, coda_export=A_.coda)


if __name__ == '__main__':
    main()
