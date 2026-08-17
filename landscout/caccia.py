# -*- coding: utf-8 -*-
"""land-scout caccia — da dove comincio a cercare.

`scan.py` sa esaminare un bbox. Ma il bbox glielo dai tu, e questo significa che
il tool non cerca: **verifica posti che hai gia' in mente**. E' il motivo per cui
l'estensione fuori dal Sannio non e' mai partita — non mancavano i dati, mancava
il primo passo.

Questo modulo lo fa al contrario: parte dalla **rete**, che e' il vincolo che non
si sposta, e restituisce le aree da scansionare in ordine di convenienza. La
logica e' quella che userebbe chiunque faccia questo mestiere:

  1. l'impianto deve connettersi → si guarda dove ci sono **sottostazioni AT/MT**;
  2. non tutte valgono: una provincia satura vale meno di una libera
     (`capacita.criticita_provincia`);
  3. dove i developer sono **gia' andati** (progetti nel portale VIA) il segnale
     e' doppio e ambiguo: conferma che il posto e' buono, e avvisa che la coda
     davanti a te e' piu' lunga. Il modulo lo dichiara invece di scegliere per te.

## Cosa NON e'

Non e' una mappa di terreni disponibili: nessun dato pubblico dice quali fondi
sono in vendita. E' un **ordine di priorita' delle aree da esaminare**, e ogni
zona che esce di qui va comunque passata a `scan.py` e poi a `blocco.py`.
E non conosce le code per nodo: quelle non sono pubbliche (v. `capacita.py`).

Uso:
    .venv/Scripts/python -m landscout.caccia --prov BN [--raggio-km 3] [--top 12]
    .venv/Scripts/python -m landscout.caccia --prov BN --comandi   # righe pronte per scan.py
"""
import json
import math
import os
import urllib.parse
import urllib.request

from . import config

OVERPASS = ['https://overpass-api.de/api/interpreter',
            'https://overpass.kumi.systems/api/interpreter',
            'https://overpass.private.coffee/api/interpreter']
UA = {'User-Agent': 'land-scout caccia'}

KV_MIN = 40_000        # sotto, e' MT: non regge un impianto utility-scale
RAGGIO_KM = 3.0        # oltre, il cavidotto mangia il vantaggio del sito
# esiti registrabili su una zona gia' esaminata
ESITI = ('scartata', 'da_riguardare', 'in_lavorazione', 'chiusa')


class ReteNonDisponibile(RuntimeError):
    """Overpass muto: nessuna zona, non 'nessuna sottostazione'."""


def _overpass(q, timeout=180, tentativi=2):
    errori = []
    for _ in range(tentativi):
        for ep in OVERPASS:
            try:
                req = urllib.request.Request(
                    ep, data=urllib.parse.urlencode({'data': q}).encode(), headers=UA)
                return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
            except Exception as e:
                errori.append(f'{ep.split("/")[2]}: {type(e).__name__}')
    raise ReteNonDisponibile('Overpass non raggiunto (' + ', '.join(errori[:3]) + ')')


def _kv(tags):
    """Tensione massima in volt dal tag OSM ('150000;20000' -> 150000)."""
    v = (tags or {}).get('voltage') or ''
    val = []
    for x in str(v).replace(',', ';').split(';'):
        try:
            val.append(int(float(x.strip())))
        except (TypeError, ValueError):
            pass
    return max(val) if val else None


def sottostazioni(prov, timeout=180, kv_min=KV_MIN):
    """Sottostazioni AT/MT della provincia, da OSM.

    Il nome della provincia va preso da `config.PROVINCE`: Overpass cerca l'area
    amministrativa per nome, e 'BN' non e' un nome.
    """
    nome = config.nome_prov(prov)
    if not nome:
        raise ValueError(f'provincia {prov!r} non riconosciuta')
    q = (f'[out:json][timeout:180];'
         f'area["boundary"="administrative"]["admin_level"="6"]["name"="{nome}"]->.a;'
         f'(node["power"="substation"](area.a);way["power"="substation"](area.a);'
         f'relation["power"="substation"](area.a););out center tags;')
    d = _overpass(q, timeout)
    out = []
    for e in d.get('elements', []):
        la = e.get('lat') or (e.get('center') or {}).get('lat')
        lo = e.get('lon') or (e.get('center') or {}).get('lon')
        if la is None or lo is None:
            continue
        tg = e.get('tags') or {}
        kv = _kv(tg)
        # senza tensione NON si scarta: OSM la omette spesso, e scartare
        # significherebbe perdere proprio le stazioni non mappate bene.
        if kv is not None and kv < kv_min:
            continue
        out.append({'nome': tg.get('name') or '(senza nome)', 'lat': la, 'lon': lo,
                    'kv': kv, 'operatore': tg.get('operator'),
                    'tensione_nota': kv is not None})
    return out


def _bbox(lat, lon, raggio_km):
    dlat = raggio_km / 111.132
    dlon = raggio_km / (111.320 * math.cos(math.radians(lat)) or 1)
    return (round(lat - dlat, 5), round(lon - dlon, 5),
            round(lat + dlat, 5), round(lon + dlon, 5))


def _km(a, b):
    (la1, lo1), (la2, lo2) = a, b
    x = (lo2 - lo1) * 111.320 * math.cos(math.radians((la1 + la2) / 2))
    y = (la2 - la1) * 111.132
    return math.hypot(x, y)


def carica_archivio(path):
    """Le zone gia' guardate, con l'esito. `{}` se il file non c'e' ancora."""
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    return d.get('zone', d) if isinstance(d, dict) else {}


def segna(archivio, se, esito, nota='', ha_utili=None, data=''):
    """Registra l'esito di una zona gia' scansionata.

    Esiti: `scartata` (guardata, non c'e' niente), `da_riguardare` (interrotta o
    dati mancanti), `in_lavorazione`, `chiusa`. Serve a una cosa sola: **non
    riscansionare la stessa area alla decima provincia**, e soprattutto non
    riscartarla per lo stesso motivo di sei mesi prima senza saperlo.
    """
    if esito not in ESITI:
        raise ValueError(f"esito '{esito}' sconosciuto: usa uno fra {', '.join(ESITI)}")
    archivio[se] = {'esito': esito, 'nota': nota, 'ha_utili': ha_utili, 'data': data}
    return archivio


def salva_archivio(archivio, path):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'zone': archivio}, f, ensure_ascii=False, indent=1)
    return path


def zone(prov, raggio_km=RAGGIO_KM, tech='agriPV', progetti=None, criticita=None,
         timeout=180, _sottostazioni=None, archivio=None, includi_viste=False):
    """Aree da scansionare, in ordine di convenienza.

    `progetti` = censimento VIA (per capire chi c'e' gia'); `criticita` = uscita di
    `capacita.criticita_provincia`. Se mancano, il punteggio si calcola lo stesso
    ma il modulo dichiara su cosa NON si e' potuto basare — mai un ordinamento
    che finge di sapere piu' di quanto sa.
    """
    # la provincia si valida QUI e non solo dentro `sottostazioni()`: chi passa
    # gia' l'elenco (i test, o una cache) salterebbe il controllo, e una sigla
    # sbagliata produrrebbe un elenco di zone attribuite a una provincia che non
    # esiste — plausibile e falso, la combinazione peggiore.
    if config.sigla_prov(prov) is None:
        raise ValueError(f'provincia {prov!r} non riconosciuta: usa una sigla '
                         f'(BN) o un nome (Benevento)')
    ss = _sottostazioni if _sottostazioni is not None else sottostazioni(prov, timeout)
    lac, gia = [], []
    if criticita is None or not (criticita or {}).get('verificato'):
        lac.append('criticita di rete della provincia NON verificata: le zone non sono '
                   'ordinate per saturazione')
    if progetti is None:
        lac.append('censimento VIA non passato: non si sa dove i developer sono gia andati')

    lv = (criticita or {}).get('livello')
    out = []
    for s in ss:
        vicini = []
        if progetti:
            for p in progetti:
                pl, pn = p.get('lat'), p.get('lon')
                if pl is None or pn is None:
                    continue
                d = _km((s['lat'], s['lon']), (pl, pn))
                if d <= max(raggio_km * 3, 10):
                    vicini.append({'nome': p.get('proponente') or p.get('nome'),
                                   'mw': p.get('mw'), 'km': round(d, 1)})
        # punteggio: la rete pesa piu' di tutto, poi la tensione, poi il presidio.
        # Non e' un voto sul terreno — li' non c'e' ancora nessun terreno.
        pt = 50.0
        motivi = []
        if lv is not None:
            pt += (4 - lv) * 12
            motivi.append(f'criticita provinciale {lv}/4')
        if s['kv']:
            pt += 10 if s['kv'] >= 100_000 else 4
            motivi.append(f"{s['kv'] // 1000} kV")
        else:
            motivi.append('tensione non nota in OSM')
        if vicini:
            pt -= min(15, 3 * len(vicini))
            motivi.append(f'{len(vicini)} progetti VIA gia in zona (posto buono, '
                          f'ma la fila davanti e piu lunga)')
        # memoria fra i run: una zona gia' guardata non si riguarda per caso, e
        # soprattutto non si riscarta per lo stesso motivo di sei mesi prima
        # senza saperlo. Resta visibile solo se lo chiedi.
        vis = (archivio or {}).get(s['nome'])
        if vis and not includi_viste:
            gia.append({'se': s['nome'], **vis})
            continue
        if vis:
            motivi.append(f"gia' vista il {vis.get('data') or '?'}: {vis['esito']}"
                          + (f" — {vis['nota']}" if vis.get('nota') else ''))
        out.append({'se': s['nome'], 'lat': s['lat'], 'lon': s['lon'], 'kv': s['kv'],
                    'bbox': _bbox(s['lat'], s['lon'], raggio_km),
                    'punteggio': round(pt, 1), 'motivi': motivi,
                    'gia_vista': vis or None,
                    'progetti_vicini': vicini[:5]})
    out.sort(key=lambda z: -z['punteggio'])
    return {'prov': config.norm_prov(prov), 'nome': config.nome_prov(prov),
            'tech': tech, 'raggio_km': raggio_km,
            'sottostazioni': len(ss), 'zone': out, 'non_verificato': lac,
            'gia_viste': gia,
            'nota': ('ordine delle aree da ESAMINARE, non elenco di terreni: nessun '
                     'dato pubblico dice quali fondi sono in vendita. Ogni zona va '
                     'passata a scan.py e poi a blocco.py.')}


def comandi(Z, min_ha=0.5, out_dir='demo'):
    """Le righe di comando pronte, in ordine. E' il ponte verso `scan.py`."""
    righe = []
    for i, z in enumerate(Z['zone'], 1):
        b = ','.join(str(x) for x in z['bbox'])
        nome = ''.join(c if c.isalnum() else '_' for c in z['se'])[:24] or f'zona{i}'
        righe.append(f".venv/Scripts/python landscout/scan.py --bbox {b} "
                     f"--tech {Z['tech']} --min-ha {min_ha} --vincoli "
                     f"--out {out_dir}/scan_{Z['prov']}_{nome}")
    return righe


def print_zone(Z, top=12):
    L = [f"CACCIA — {Z['nome']} ({Z['prov']}) · {Z['sottostazioni']} sottostazioni AT "
         f"· raggio {Z['raggio_km']} km"]
    for i, z in enumerate(Z['zone'][:top], 1):
        L.append(f"  {i:2d}. {z['punteggio']:5.1f}  {z['se'][:30]:<30s} "
                 f"{z['lat']:.4f},{z['lon']:.4f}")
        L.append(f"       {' · '.join(z['motivi'])}")
        L.append(f"       bbox {','.join(str(x) for x in z['bbox'])}")
    if Z.get('gia_viste'):
        L.append(f"  {len(Z['gia_viste'])} zone SALTATE perche' gia' esaminate: "
                 + ', '.join(f"{g['se']} ({g['esito']})" for g in Z['gia_viste'][:6]))
    for x in Z['non_verificato']:
        L.append(f'  ? {x}')
    L.append('  ' + Z['nota'])
    return '\n'.join(L)


def main():
    import argparse
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='Da dove cominciare a cercare terra.')
    ap.add_argument('--prov', required=True, help='sigla o nome provincia')
    ap.add_argument('--raggio-km', type=float, default=RAGGIO_KM, dest='raggio')
    ap.add_argument('--tech', default='agriPV', choices=['agriPV', 'BESS'])
    ap.add_argument('--top', type=int, default=12)
    ap.add_argument('--comandi', action='store_true', help='stampa le righe per scan.py')
    ap.add_argument('--out', default=None, help='salva il risultato in JSON')
    ap.add_argument('--archivio', default=None,
                    help='JSON delle zone gia esaminate: quelle registrate non '
                         'ricompaiono (ma vengono dichiarate)')
    ap.add_argument('--includi-viste', action='store_true', dest='includi_viste')
    ap.add_argument('--segna', default=None,
                    help='"SE Morcone=scartata" — registra l esito di una zona '
                         'nell archivio (' + ' | '.join(ESITI) + ')')
    ap.add_argument('--nota', default='')
    A = ap.parse_args()

    if A.segna:
        if not A.archivio:
            raise SystemExit('--segna richiede --archivio')
        from datetime import date as _d
        arch = carica_archivio(A.archivio)
        se, _, esito = A.segna.partition('=')
        segna(arch, se.strip(), esito.strip(), nota=A.nota,
              data=_d.today().isoformat())
        salva_archivio(arch, A.archivio)
        print(f"registrato: {se.strip()} -> {esito.strip()}  ({A.archivio})")
        return

    crit = None
    try:
        from . import capacita as CAP
        crit = CAP.criticita_provincia(config.nome_prov(A.prov),
                                       cod_pro=config.cod_prov(A.prov))
    except Exception as e:
        print(f'   criticita non letta ({type(e).__name__})')
    progetti = None
    try:
        from . import match as M
        cache = M.load_cache()
        progetti = [p for p in (M.KNOWN if isinstance(M.KNOWN, list) else [])] or None
    except Exception:
        progetti = None

    Z = zone(A.prov, raggio_km=A.raggio, tech=A.tech, progetti=progetti, criticita=crit,
             archivio=carica_archivio(A.archivio), includi_viste=A.includi_viste)
    print(print_zone(Z, top=A.top))
    if A.comandi:
        print('\n--- da lanciare, in ordine ---')
        for r in comandi(Z)[:A.top]:
            print(r)
    if A.out:
        json.dump(Z, open(A.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\nscritto: {A.out}')


if __name__ == '__main__':
    main()
