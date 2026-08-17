# -*- coding: utf-8 -*-
"""land-scout comparabili — il prezzo vero viene da vicino, non da una media.

Il tool aveva una sola idea di "mercato": `EUR_HA_MERCATO_RINNOVABILI = 25.000-50.000
EUR/ha`, una banda nazionale scritta nel codice. E' servita finche' non c'era altro,
ma il 10/08/2026 e' venuto fuori il difetto: **a Morcone esiste un comparabile
diretto** — RWE ha comprato in piena proprieta' nel 2024 a 68.660 EUR/ha — e il tool
continuava a proporre 25-50k, cioe' meno della meta' di cio' che un compratore vero
ha pagato a poche centinaia di metri.

Un comparabile osservato vicino batte sempre una banda nazionale stimata. Il punto
non e' che 25-50k sia sbagliato: e' che **non e' il dato migliore disponibile**, e
usarlo senza dire che ne esiste uno piu' vicino e' la stessa famiglia di errore del
"non verificato scambiato per pulito".

## Le tre cose che questo registro impone

1. **La provenienza viaggia col numero.** Ogni comparabile porta fonte, data,
   superficie, tipo di diritto e a cosa serviva il terreno. Un acquisto per una
   piattaforma di accumulo accanto alla sottostazione non e' il prezzo di sette
   ettari di agrivoltaico sparso: e' un ottimo argomento, non un'equivalenza.
2. **La rivalutazione e' esplicita.** Un prezzo del 2024 in euro 2026 non e' lo
   stesso numero. Se non si dichiara l'indice, non si rivaluta.
3. **Se non c'e' un comparabile, si dice che si sta usando una banda generica.**

Uso:
    from landscout import comparabili as CP
    CP.registra('Morcone (BN)', 68660, anno=2024, ha=1.29, tipo='vendita piena',
                acquirente='RWE', uso='piattaforma/adiacenza SE', fonte='atto 2024')
    CP.banda('Morcone (BN)', anno_target=2026, istat_annuo=0.017)
"""
import json
import os
from datetime import date

from .config import RAW

REGISTRO = os.path.join(str(RAW), 'comparabili', 'comparabili.json')

# Banda nazionale di prassi: l'ultima risorsa, non la prima.
BANDA_NAZIONALE = (25_000, 50_000)


def _carica():
    if not os.path.exists(REGISTRO):
        return {'comparabili': []}
    with open(REGISTRO, encoding='utf-8') as f:
        return json.load(f)


def _salva(d):
    os.makedirs(os.path.dirname(REGISTRO), exist_ok=True)
    with open(REGISTRO, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    return REGISTRO


def registra(zona, eur_ha, anno, ha=None, tipo='vendita piena', acquirente=None,
             uso=None, fonte=None, affidabilita='osservato', nota=None):
    """Aggiunge (o aggiorna) un comparabile. `fonte` non e' opzionale nei fatti:
    un prezzo senza provenienza vale quanto una banda inventata."""
    if not fonte:
        raise ValueError('un comparabile senza fonte non e un comparabile: '
                         'da dove viene questo prezzo?')
    if affidabilita not in ('osservato', 'riferito', 'stimato'):
        raise ValueError("affidabilita: 'osservato' | 'riferito' | 'stimato'")
    d = _carica()
    voce = {'zona': zona, 'eur_ha': round(float(eur_ha)), 'anno': int(anno),
            'ha': ha, 'tipo': tipo, 'acquirente': acquirente, 'uso': uso,
            'fonte': fonte, 'affidabilita': affidabilita, 'nota': nota}
    d['comparabili'] = [c for c in d['comparabili']
                        if not (c['zona'] == zona and c['anno'] == int(anno)
                                and c.get('acquirente') == acquirente)]
    d['comparabili'].append(voce)
    d['comparabili'].sort(key=lambda c: (c['zona'], -c['anno']))
    _salva(d)
    return voce


def cerca(zona=None):
    """Comparabili della zona (confronto sul testo, tollerante)."""
    d = _carica()
    if not zona:
        return d['comparabili']
    z = str(zona).strip().upper()
    return [c for c in d['comparabili']
            if z in c['zona'].upper() or c['zona'].upper() in z]


def rivaluta(eur, anno_da, anno_a=None, istat_annuo=None):
    """Porta un prezzo a euro correnti. Senza indice dichiarato NON rivaluta.

    Inventare un'inflazione e' peggio che lasciare il numero vecchio: il numero
    vecchio almeno si vede che e' vecchio.
    """
    anno_a = anno_a or date.today().year
    if istat_annuo is None or anno_a <= anno_da:
        return {'eur': round(eur), 'rivalutato': False, 'anno': anno_da,
                'nota': ('nessun indice dichiarato: prezzo lasciato in euro '
                         f'{anno_da}, da rivalutare a mano')}
    n = anno_a - anno_da
    v = eur * (1 + istat_annuo) ** n
    return {'eur': round(v), 'rivalutato': True, 'anno': anno_a,
            'da': round(eur), 'anni': n, 'istat_annuo': istat_annuo,
            'nota': f'rivalutato {n} anni al {istat_annuo:.1%}/anno [indice DICHIARATO, '
                    f'non verificato su serie ISTAT]'}


def banda(zona=None, anno_target=None, istat_annuo=None, nazionale=BANDA_NAZIONALE):
    """La banda di prezzo migliore disponibile per la zona, con la sua provenienza.

    Se esiste almeno un comparabile locale, quello vince sulla banda nazionale — e
    il risultato dichiara quale dei due si sta usando, sempre.
    """
    loc = [c for c in cerca(zona) if c['affidabilita'] in ('osservato', 'riferito')]
    if not loc:
        return {'lo': nazionale[0], 'hi': nazionale[1], 'fonte': 'banda nazionale di prassi',
                'locale': False, 'comparabili': [],
                'nota': ('nessun comparabile registrato per questa zona: si usa una banda '
                         'generica. Un solo atto vicino varrebbe piu di questa forbice.')}
    val = []
    for c in loc:
        r = rivaluta(c['eur_ha'], c['anno'], anno_target, istat_annuo)
        val.append(dict(c, eur_ha_corrente=r['eur'], rivalutazione=r))
    prezzi = [c['eur_ha_corrente'] for c in val]
    avvisi = []
    diversi = {c.get('uso') for c in val if c.get('uso')}
    if diversi:
        avvisi.append('i comparabili riguardano: ' + ' · '.join(sorted(diversi))
                      + ' — verificare che l uso sia paragonabile al tuo')
    if any(not c['rivalutazione']['rivalutato'] for c in val):
        avvisi.append('almeno un comparabile non e stato rivalutato: manca l indice')
    return {'lo': min(prezzi), 'hi': max(prezzi), 'locale': True,
            'fonte': f'{len(val)} comparabile/i locale/i',
            'comparabili': val, 'nazionale': nazionale, 'avvisi': avvisi,
            'nota': ('comparabile locale: batte la banda nazionale, ma vale per il tipo '
                     'di terreno e di uso a cui si riferisce, non per ogni ettaro.')}


def print_banda(b):
    L = [f"PREZZO DI RIFERIMENTO: {b['lo']:,} – {b['hi']:,} EUR/ha  ({b['fonte']})"
         .replace(',', '.')]
    for c in b.get('comparabili', []):
        r = c['rivalutazione']
        riga = (f"  {c['anno']} · {c['eur_ha']:,} EUR/ha".replace(',', '.')
                + (f" -> {r['eur']:,} in euro {r['anno']}".replace(',', '.')
                   if r['rivalutato'] else ' (non rivalutato)'))
        if c.get('ha'):
            riga += f" · {c['ha']} ha"
        if c.get('acquirente'):
            riga += f" · {c['acquirente']}"
        L.append(riga)
        L.append(f"      {c['tipo']}" + (f" · uso: {c['uso']}" if c.get('uso') else '')
                 + f" · fonte: {c['fonte']} [{c['affidabilita']}]")
    if not b['locale']:
        L.append(f"  banda nazionale {b['lo']:,}-{b['hi']:,}".replace(',', '.'))
    for x in b.get('avvisi', []):
        L.append(f'  ! {x}')
    L.append('  ' + b['nota'])
    return '\n'.join(L)


def main():
    import argparse
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='Comparabili di prezzo per zona.')
    ap.add_argument('--zona', default=None)
    ap.add_argument('--registra', action='store_true')
    ap.add_argument('--eur-ha', type=float, dest='eur_ha')
    ap.add_argument('--anno', type=int)
    ap.add_argument('--ha', type=float, default=None)
    ap.add_argument('--tipo', default='vendita piena')
    ap.add_argument('--acquirente', default=None)
    ap.add_argument('--uso', default=None)
    ap.add_argument('--fonte', default=None)
    ap.add_argument('--istat', type=float, default=None,
                    help='indice annuo per la rivalutazione (es. 0.017)')
    A = ap.parse_args()
    if A.registra:
        v = registra(A.zona, A.eur_ha, A.anno, ha=A.ha, tipo=A.tipo,
                     acquirente=A.acquirente, uso=A.uso, fonte=A.fonte)
        print('registrato:', json.dumps(v, ensure_ascii=False))
        return
    print(print_banda(banda(A.zona, istat_annuo=A.istat)))


if __name__ == '__main__':
    main()
