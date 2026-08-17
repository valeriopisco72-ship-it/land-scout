# -*- coding: utf-8 -*-
"""land-scout portafoglio — dal pool a PIU' blocchi, senza venderne uno due volte.

Il tool sapeva costruire **un** blocco: gli davi un pool e delle ancore e ti
restituiva il miglior aggregato attorno a quelle. Va benissimo quando il sito e'
gia' deciso — Morcone, la terra dei nonni. Non basta per fare origination, che e'
il mestiere opposto: da un pool di centinaia di ettari servono **N siti
indipendenti**, ciascuno vendibile da solo, e serve sapere quanto pool e' rimasto
fuori e perche'.

Farlo a mano, lanciando `blocco` piu' volte, ha un difetto che non si vede finche'
non fa danno: **le particelle si ripetono**. Due blocchi che condividono un fondo
non sono due siti, sono un sito contato due volte — e se finiscono in due teaser
diversi, e' la stessa terra promessa a due developer. Qui la non-sovrapposizione
e' un invariante, non una speranza: si costruisce a pool calante e si ricontrolla
alla fine.

## Cosa fa in piu' della greedy ingenua

Costruire "il migliore, poi il migliore di quel che resta" e' miope: il primo
blocco puo' spezzare in due un'isola e lasciare due mezzi blocchi inutilizzabili.
Il modulo prova **piu' ordini di costruzione** (massimizzando prima la terra
propria, oppure prima il risparmio di controparti) e tiene il portafoglio
migliore nel complesso, non il primo blocco migliore. La differenza si vede
quando le ancore stanno tutte in un'isola sola.

## Cosa NON fa, e va letto prima dei numeri

* **Non sa se la terra e' in vendita.** Nessun dato pubblico lo dice. Un blocco
  qui e' un'ipotesi di aggregazione, non un'offerta.
* **Non conosce rete ne' prezzo** se non glieli passi: la classifica ordina per
  ettari e per **firme necessarie**, che e' il costo vero dell'aggregazione, e lo
  dichiara. Un blocco grande a 8 km da una cabina puo' valere meno di uno piccolo
  attaccato: quel confronto lo fa `bancabilita`, non questo modulo.
* **Non decide quando fermarsi al posto tuo**: dice quanto pool e' avanzato e in
  che isole, cosi' "tre blocchi su 391 ha" non si legge come "il pool e' finito".

Uso:
    from landscout import blocco as BL, portafoglio as PF
    A = BL.ammissibilita(parcels, vincoli, occupazione)
    P = PF.costruisci(A, target_ha=25, n_max=4, ancore=ancore_ids)
    print(PF.print_portafoglio(P))
"""
import json
import os
from collections import defaultdict

from . import blocco as BL

# un blocco sotto questa quota del target non e' un sito: e' un residuo.
QUOTA_MIN = 0.55
# ordini di costruzione provati. Non e' un parametro da tarare: sono le due
# domande diverse che un proprietario e un developer fanno allo stesso pool.
ORDINI = ('ancore', 'controparti')

# Sotto questa soglia l'aggregato esiste sulla mappa ma non nella realta': servono
# piu' di 1,3 controparti per ettaro, cioe' una trattativa ogni 7.500 mq. ⚠️ E' una
# soglia STIMATA — non un dato di mercato osservato — e serve solo a ordinare le
# priorita': un blocco cosi' non va scartato dal tool, va guardato in faccia da
# chi decide se ha il tempo di bussare a quaranta porte.
HA_PER_FIRMA_MIN = 0.75

# Oltre questa distanza dalla rete il cavidotto si mangia il vantaggio del sito.
# Non e' un numero nuovo: e' lo stesso raggio con cui `caccia` sceglie le zone da
# esaminare attorno a una sottostazione, e restare coerenti conta piu' che
# affinarlo (3 km di cavidotto interrato sono ordine di grandezza 300-600 k EUR).
RAGGIO_RETE_KM = 3.0


class DirettivaNonRispettata(RuntimeError):
    """Una direttiva dell'utente non e' soddisfacibile su questo pool.

    Esiste perche' il tool ha fatto la cosa sbagliata: gli si diceva "la terra di
    famiglia deve esserci TUTTA" e restituiva blocchi che ne lasciavano fuori un
    pezzo, con un avviso in coda. Un avviso in coda a un risultato sbagliato e'
    peggio di un errore: il risultato si usa lo stesso, l'avviso si legge dopo.
    Quando una direttiva e' dichiarata obbligatoria, o e' rispettata o si alza
    questa — con l'elenco di cio' che manca e il perche'.
    """


def _chiave(p):
    return f"{p.get('fg')}_{p.get('pla')}"


def _adj_viva(adj, vivi):
    """Adiacenza ristretta ai nodi ancora disponibili.

    Si filtra il GRAFO, non la lista delle particelle: cosi' gli indici restano
    quelli di `A['ammesse']` e non serve rimappare niente. Rimappare indici fra
    una passata e l'altra e' esattamente il modo in cui un blocco finisce per
    contenere la particella di un altro."""
    out = defaultdict(set)
    for i in vivi:
        out[i] = set(adj.get(i, ())) & vivi
    return out


def _una_passata(A, adj, target_ha, n_max, ancore, quota_min, obiettivo, tolleranza):
    P = A['ammesse'] if isinstance(A, dict) else A
    vivi = set(range(len(P)))
    anc = set(ancore or ())
    blocchi = []
    motivo = f'raggiunti i {n_max} blocchi richiesti'
    for _ in range(max(0, n_max)):
        av = _adj_viva(adj, vivi)
        anc_vive = anc & vivi
        semi = (sorted(anc_vive) if (anc_vive and obiettivo == 'ancore')
                else sorted(vivi, key=lambda i: -P[i]['netti'])[:50])
        if not semi:
            motivo = 'pool esaurito: nessun seme disponibile'
            break
        blk = BL.cresci_migliore(A, av, target_ha, ancore=anc_vive, semi=semi,
                                 tolleranza=quota_min, obiettivo=obiettivo)
        if blk is None or blk['ha_netti'] < target_ha * quota_min:
            motivo = (f'nessun altro aggregato raggiunge il {quota_min:.0%} del target '
                      f'({target_ha:g} ha): il pool residuo e frammentato')
            break
        prese = {_chiave(q) for q in blk['particelle']}
        idx = {i for i in vivi if _chiave(P[i]) in prese}
        if not idx:
            motivo = 'blocco senza corrispondenza nel pool: interrotto'
            break
        blk['sotto_target'] = blk['ha_netti'] < target_ha * tolleranza
        blocchi.append(blk)
        vivi -= idx
    return blocchi, vivi, motivo


def _valore(blocchi):
    """Come si confrontano due portafogli interi. Ettari totali prima di tutto —
    un developer compra MW — e a parita' vince quello che li ottiene con meno
    firme, perche' ogni firma e' una trattativa che puo' non arrivare."""
    ha = sum(b['ha_netti'] for b in blocchi)
    firme = sum(b['n_acquisti'] for b in blocchi)
    return (round(ha, 2), -firme, len(blocchi))


def costruisci(A, adj=None, target_ha=25.0, n_max=4, ancore=(), quota_min=QUOTA_MIN,
               tolleranza=0.98, ordini=ORDINI, comune='', prov=None, verbose=True,
               ancore_obbligatorie=False):
    """N blocchi indipendenti dallo stesso pool, senza particelle ripetute.

    `ancore_obbligatorie=True` rende le ancore un **vincolo**, non una preferenza:
    o tutte le particelle gia' controllate finiscono dentro un blocco, o la
    funzione alza `DirettivaNonRispettata`. Senza questo il portafoglio usciva
    lo stesso, con la terra di famiglia a meta' e un avviso in fondo — che e' il
    modo in cui uno strumento aggira chi lo usa.
    """
    P = A['ammesse'] if isinstance(A, dict) else A
    if adj is None:
        adj = BL.adiacenza(A)
    anc0 = set(ancore or ())
    if ancore_obbligatorie and not anc0:
        raise DirettivaNonRispettata(
            'ancore_obbligatorie=True ma non e stata passata nessuna ancora: '
            'la direttiva non e verificabile, quindi non si finge di rispettarla')
    prove = []
    for ordine in (ordini or ORDINI):
        b, vivi, motivo = _una_passata(A, adj, target_ha, n_max, ancore,
                                       quota_min, ordine, tolleranza)
        prove.append({'ordine': ordine, 'blocchi': b, 'vivi': vivi,
                      'motivo': motivo, 'valore': _valore(b)})
        if verbose:
            print(f"  ordine '{ordine}': {len(b)} blocchi · "
                  f"{sum(x['ha_netti'] for x in b):.2f} ha · "
                  f"{sum(x['n_acquisti'] for x in b)} firme")
    prove.sort(key=lambda x: x['valore'], reverse=True)
    v = prove[0]

    ha_pool = round(sum(p['netti'] for p in P), 2)
    ha_bloc = round(sum(b['ha_netti'] for b in v['blocchi']), 2)
    anc = set(ancore or ())
    anc_fuori = sorted(anc & v['vivi'])
    isole = BL.componenti({'ammesse': P}, _adj_viva(adj, v['vivi']))
    isole = [c for c in isole if set(c) <= v['vivi']]

    R = {'comune': comune, 'prov': prov, 'target_ha': target_ha,
         'ordine_scelto': v['ordine'], 'motivo_stop': v['motivo'],
         'n_blocchi': len(v['blocchi']), 'blocchi': v['blocchi'],
         'ha_pool': ha_pool, 'ha_in_blocchi': ha_bloc,
         'pct_pool_usato': round(100 * ha_bloc / ha_pool, 1) if ha_pool else 0.0,
         'firme_totali': sum(b['n_acquisti'] for b in v['blocchi']),
         'ha_ancore_in_blocchi': round(sum(b['ha_ancore'] for b in v['blocchi']), 2),
         'ancore_fuori': [_chiave(P[i]) for i in anc_fuori],
         'residuo_isole': [{'n': len(c), 'ha': round(sum(P[i]['netti'] for i in c), 2)}
                           for c in isole[:5]],
         'ha_residuo': round(sum(P[i]['netti'] for i in v['vivi']), 2),
         'prove': [{'ordine': p['ordine'], 'n': len(p['blocchi']),
                    'ha': p['valore'][0], 'firme': -p['valore'][1]} for p in prove],
         'avvisi': [], 'nota': (
             'un blocco qui e un IPOTESI di aggregazione: nessuna fonte pubblica dice '
             'quali fondi siano in vendita. La classifica ordina per ettari e per firme '
             'necessarie, e NON conosce rete ne prezzo: quel confronto lo fa bancabilita.')}

    R['ancore_obbligatorie'] = bool(ancore_obbligatorie)
    R = classifica(R)
    sov = verifica_sovrapposizioni(R['blocchi'])
    R['sovrapposizioni'] = sov
    if sov:
        R['avvisi'].append(
            f'{len(sov)} particelle compaiono in PIU di un blocco: e la stessa terra '
            f'contata due volte — va risolto prima di mandare qualunque teaser')
    if anc_fuori and ancore_obbligatorie:
        # niente risultato parziale: la direttiva era un vincolo.
        raise DirettivaNonRispettata(
            f'{len(anc_fuori)} particelle gia tue non entrano in nessun blocco con '
            f'target {target_ha:g} ha e {n_max} blocchi: '
            f'{", ".join(R["ancore_fuori"][:10])}'
            + (f' e altre {len(anc_fuori) - 10}' if len(anc_fuori) > 10 else '')
            + '. Sono scollegate dal resto o troppo lontane. Le strade sono tre: '
              'usare blocco.copri_ancore() che costruisce SOTTOBLOCCHI contigui '
              'attorno a tutte le ancore, alzare n_max, oppure abbassare target_ha')
    if anc_fuori:
        R['avvisi'].append(
            f'{len(anc_fuori)} particelle gia tue sono rimaste FUORI dai blocchi '
            f'({", ".join(R["ancore_fuori"][:6])}): se devono starci tutte, la funzione '
            f'giusta e blocco.copri_ancore(), non questa')
    sotto = [b for b in R['blocchi'] if b.get('sotto_target')]
    if sotto:
        R['avvisi'].append(
            f'{len(sotto)} blocchi sotto il target di {target_ha:g} ha: sono siti veri '
            f'solo se il developer accetta quella taglia')
    cari = [b for b in R['blocchi'] if b['n_acquisti']
            and b['ha_per_firma'] < HA_PER_FIRMA_MIN]
    if cari:
        R['avvisi'].append(
            f'{len(cari)} blocchi costano piu di 1,3 controparti per ettaro '
            f'({", ".join(f"{b["sito"]}: {b["n_acquisti"]} firme per {b["ha_netti"]:.0f} ha" for b in cari[:3])}): '
            f'esistono sulla mappa, non e detto che esistano come trattativa. '
            f'Soglia STIMATA ({HA_PER_FIRMA_MIN} ha/firma), non osservata sul mercato')
    if ha_pool and R['pct_pool_usato'] < 50:
        R['avvisi'].append(
            f'solo il {R["pct_pool_usato"]:.0f}% del pool e finito nei blocchi: '
            f'{R["ha_residuo"]:.0f} ha restano fuori, in {len(isole)} isole scollegate')
    return R


def arricchisci_rete(R, margine_deg=(0.055, 0.07), verbose=True, _distanze=None):
    """Attacca a ogni blocco la distanza da sottostazione e linea AT.

    E' la domanda che un developer fa per prima e che il portafoglio, da solo,
    non sa: un blocco grande a 8 km da una cabina vale meno di uno piccolo
    attaccato. Una sola interrogazione per tutto il portafoglio (v.
    `rete.distanze_multi`), non una per blocco.

    Se la rete non risponde, ogni blocco resta `rete_verificata=False`: **non
    "vicino"**, non `None` che poi qualcuno legge come zero.
    """
    if not R.get('blocchi'):
        return R
    gruppi = {}
    for b in R['blocchi']:
        pts = [(q[0], q[1]) for p in b.get('particelle') or []
               for q in (p.get('poly') or [])]
        gruppi[b['sito']] = pts
    if _distanze is not None:
        D = _distanze
    else:
        from . import rete as RT
        D = RT.distanze_multi(gruppi, margine_deg=margine_deg)
    lontani, muti = [], []
    for b in R['blocchi']:
        d = D.get(b['sito']) or {}
        b['rete_verificata'] = bool(d.get('verificato'))
        b['d_se_m'] = d.get('d_se_m')
        b['d_linea_m'] = d.get('d_linea_m')
        b['linea_kv'] = d.get('linea_kv')
        if not b['rete_verificata']:
            muti.append(b['sito'])
        elif b['d_se_m'] is not None and b['d_se_m'] > RAGGIO_RETE_KM * 1000:
            lontani.append(b)
    R['rete_letta'] = any(b.get('rete_verificata') for b in R['blocchi'])
    if muti:
        R['avvisi'].append(
            f'distanza dalla rete NON verificata per {len(muti)} blocchi '
            f'({", ".join(muti[:4])}): non significa vicini — significa che non si sa')
    if lontani:
        R['avvisi'].append(
            f'{len(lontani)} blocchi oltre {RAGGIO_RETE_KM:g} km dalla sottostazione piu '
            f'vicina (' + ', '.join(f"{b['sito']}: {b['d_se_m']/1000:.1f} km"
                                    for b in lontani[:3])
            + '): il cavidotto si mangia il vantaggio del sito')
    if verbose:
        for b in R['blocchi']:
            d = (f"{b['d_se_m']/1000:.2f} km" if b.get('d_se_m') is not None
                 else ('non verificata' if not b.get('rete_verificata') else 'nessuna SE nel raggio'))
            print(f"  {b['sito']:<14s} SE {d}")
    return R


def classifica(R, chiave='ettari'):
    """Ordina i blocchi e attacca a ciascuno i numeri con cui e' stato ordinato.

    chiave='ettari' → prima i piu' grandi (quello che compra un developer)
    chiave='firme'  → prima quelli che costano meno trattative
    chiave='rete'   → prima i piu' vicini alla sottostazione (serve
                      `arricchisci_rete`; i non misurati finiscono in fondo)
    """
    for b in R['blocchi']:
        b['ha_per_firma'] = round(b['ha_netti'] / max(1, b['n_acquisti']), 2)
        b['quota_tua_pct'] = (round(100 * b['ha_ancore'] / b['ha_netti'], 1)
                              if b['ha_netti'] else 0.0)
    if chiave == 'firme':
        R['blocchi'].sort(key=lambda b: (-b['ha_per_firma'], -b['ha_netti']))
    elif chiave == 'rete':
        # i blocchi senza misura vanno IN FONDO, non davanti: un dato mancante
        # non e' una distanza buona. E si ordina per distanza, non per ettari.
        R['blocchi'].sort(key=lambda b: (b.get('d_se_m') is None,
                                         b.get('d_se_m') or 0, -b['ha_netti']))
    else:
        R['blocchi'].sort(key=lambda b: (-b['ha_netti'], -b['ha_per_firma']))
    base = (R.get('comune') or 'sito').strip()[:12] or 'sito'
    for i, b in enumerate(R['blocchi'], 1):
        b['rango'] = i
        b['sito'] = f'{base}-{i}'
    R['ordinato_per'] = chiave
    return R


def verifica_sovrapposizioni(blocchi):
    """Particelle presenti in piu' di un blocco. Deve essere sempre vuoto.

    Accetta anche blocchi che arrivano da file diversi (portafogli di sessioni
    diverse, o due comuni confinanti): e' li' che la ripetizione scappa, perche'
    dentro una singola passata il pool cala e non puo' succedere.
    """
    dove = defaultdict(list)
    for n, b in enumerate(blocchi):
        nome = b.get('sito') or b.get('titolo') or f'blocco{n}'
        for p in b.get('particelle') or []:
            dove[_chiave(p)].append(nome)
    return {k: v for k, v in sorted(dove.items()) if len(v) > 1}


def unisci(portafogli, comune=''):
    """Fonde piu' portafogli in uno solo, DICHIARANDO le sovrapposizioni.

    Non le risolve: quale blocco debba tenere una particella contesa e' una
    decisione commerciale, non un problema di ordinamento.
    """
    blocchi = []
    for R in portafogli:
        for b in (R.get('blocchi') or []):
            b = dict(b)
            b['origine'] = R.get('comune') or ''
            blocchi.append(b)
    out = {'comune': comune, 'prov': None, 'n_blocchi': len(blocchi), 'blocchi': blocchi,
           'ha_in_blocchi': round(sum(b['ha_netti'] for b in blocchi), 2),
           'firme_totali': sum(b['n_acquisti'] for b in blocchi),
           'ha_pool': round(sum(R.get('ha_pool') or 0 for R in portafogli), 2),
           'ha_residuo': round(sum(R.get('ha_residuo') or 0 for R in portafogli), 2),
           'ha_ancore_in_blocchi': round(sum(b['ha_ancore'] for b in blocchi), 2),
           'residuo_isole': [], 'ancore_fuori': [], 'prove': [], 'avvisi': [],
           'motivo_stop': 'unione di portafogli gia costruiti',
           'target_ha': None, 'ordine_scelto': None,
           'nota': 'portafoglio unito: i blocchi vengono da passate diverse'}
    out['pct_pool_usato'] = (round(100 * out['ha_in_blocchi'] / out['ha_pool'], 1)
                             if out['ha_pool'] else 0.0)
    # la classifica rinomina i siti: le sovrapposizioni si cercano PRIMA, coi
    # nomi di origine, altrimenti il messaggio indica due blocchi che non
    # esistevano quando la particella e' finita in tutti e due.
    sov = verifica_sovrapposizioni(blocchi)
    out = classifica(out)
    out['sovrapposizioni'] = sov
    if sov:
        out['avvisi'].append(
            f'{len(sov)} particelle compaiono in blocchi di portafogli diversi: '
            + '; '.join(f'{k} in {" e ".join(v)}' for k, v in list(sov.items())[:4]))
    return out


def salva(R, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(R, f, ensure_ascii=False, indent=1)
    return path


def carica(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def print_portafoglio(R, top=10):
    L = [f"PORTAFOGLIO {R.get('comune') or ''} — {R['n_blocchi']} blocchi · "
         f"{R['ha_in_blocchi']} ha su {R['ha_pool']} di pool "
         f"({R['pct_pool_usato']}%) · {R['firme_totali']} firme".rstrip()]
    if R.get('ordine_scelto'):
        L.append(f"  ordine scelto '{R['ordine_scelto']}' fra "
                 + ' · '.join(f"{p['ordine']}: {p['n']} blocchi/{p['ha']} ha/"
                              f"{p['firme']} firme" for p in (R.get('prove') or [])))
    rete = R.get('rete_letta')
    L.append(f"  {'sito':<14s} {'ha':>7s} {'tuoi':>6s} {'quota':>6s} {'firme':>6s} "
             f"{'ha/firma':>9s}" + (f" {'SE km':>7s}" if rete else ''))
    for b in R['blocchi'][:top]:
        riga = (f"  {b.get('sito', '?'):<14s} {b['ha_netti']:7.2f} {b['ha_ancore']:6.2f} "
                f"{b.get('quota_tua_pct', 0):5.0f}% {b['n_acquisti']:6d} "
                f"{b.get('ha_per_firma', 0):9.2f}")
        if rete:
            riga += (f" {b['d_se_m']/1000:7.2f}" if b.get('d_se_m') is not None
                     else f" {'n.v.':>7s}")
        L.append(riga + ('  (sotto target)' if b.get('sotto_target') else ''))
    if R.get('residuo_isole'):
        L.append(f"  residuo: {R['ha_residuo']} ha in isole da "
                 + ', '.join(f"{i['ha']} ha" for i in R['residuo_isole']))
    L.append(f"  stop: {R['motivo_stop']}")
    for a in (R.get('avvisi') or []):
        L.append(f'  ! {a}')
    L.append('  ' + R['nota'])
    return '\n'.join(L)


def main():
    import argparse
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='Piu blocchi indipendenti dallo stesso pool.')
    ap.add_argument('--scan', required=True, help='output di scan.py')
    ap.add_argument('--comune', default='')
    ap.add_argument('--prov', default=None)
    ap.add_argument('--target-ha', type=float, default=25.0)
    ap.add_argument('--blocchi', type=int, default=4)
    ap.add_argument('--ancore', default='', help='fg/pla separati da virgola')
    ap.add_argument('--ordina', choices=('ettari', 'firme'), default='ettari')
    ap.add_argument('--out', default=None)
    Ar = ap.parse_args()
    A = BL.da_scan(Ar.scan, comune=Ar.comune or None)
    P = A['ammesse']
    voluti = {x.strip().replace('/', '_') for x in Ar.ancore.split(',') if x.strip()}
    ancore = [i for i, p in enumerate(P) if _chiave(p) in voluti]
    if voluti and not ancore:
        print(f'  ! nessuna delle {len(voluti)} ancore richieste e nel pool ammesso')
    R = costruisci(A, target_ha=Ar.target_ha, n_max=Ar.blocchi, ancore=ancore,
                   comune=Ar.comune, prov=Ar.prov)
    R = classifica(R, Ar.ordina)
    print(print_portafoglio(R))
    if Ar.out:
        print(f'  scritto: {salva(R, Ar.out)}')


if __name__ == '__main__':
    main()
