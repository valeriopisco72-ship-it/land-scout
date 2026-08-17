# -*- coding: utf-8 -*-
"""land-scout fuoco — aree percorse dal fuoco (L. 353/2000).

E' il vincolo con il rapporto danno/visibilita' peggiore di tutti: **non compare
in nessuna cartografia dei vincoli**, sta in un albo comunale che spesso e' un
PDF, e se morde uccide il progetto per anni. La L. 353/2000 art. 10 c.1 vieta
sulle zone boscate e sui pascoli percorsi dal fuoco:
  * il cambio di destinazione per **15 anni**;
  * l'edificazione per **10 anni**;
  * e per **5 anni** sono vietate attivita' di rimboschimento/ingegneria
    ambientale finanziate con risorse pubbliche.
Un blocco che ci ricade non e' un blocco con un problema: e' un blocco morto,
e non lo si scopre da nessun layer regionale.

## Cosa fa questo modulo, e cosa NON puo' fare

Interroga **EFFIS / Copernicus** (European Forest Fire Information System), che
mappa i perimetri delle aree bruciate da satellite dal 2000 in poi, con soglia
di rilevamento intorno ai **30 ettari**. Verificato il 10/08/2026:
`maps.effis.emergency.copernicus.eu/effis`, layer `modis.ba.poly`, che **ha una
dimensione TIME** (`2000-01-01/2099-12-31`) — quindi si puo' interrogare anno per
anno, ed e' esattamente cio' che serve per una finestra di 10-15 anni. In GML
tornano `FIREDATE`, `FINALDATE`, `AREA_HA`, `COMMUNE`, `PROVINCE`.

⚠️ **EFFIS non sostituisce il catasto incendi comunale**, per tre ragioni che
vanno dette a chi legge il risultato:
  1. **la soglia**: sotto ~30 ha un incendio puo' non essere rilevato, e un
     incendio da 5 ettari sul fondo giusto basta a bloccarlo;
  2. **il perimetro giuridico e' quello del Comune**, rilevato a terra e
     approvato con delibera — EFFIS e' un'osservazione satellitare;
  3. il vincolo riguarda **zone boscate e pascoli**: un seminativo bruciato non
     ricade nel divieto di cambio destinazione. Il modulo riporta la quota
     agricola del perimetro (`AGRIAREAS`) ma **non decide** al posto del tecnico.
Quindi: **un esito negativo qui non e' un via libera** — e' l'assenza di un
incendio *grande* in quel punto. L'albo pretorio del Comune resta obbligatorio,
e il modulo lo scrive in ogni output.

Uso:
    from landscout import fuoco
    r = fuoco.storico(particelle, anni=15)
    print(fuoco.print_report(r))
"""
import re
import urllib.parse
import urllib.request
from datetime import date

EFFIS = 'https://maps.effis.emergency.copernicus.eu/effis'
LAYER = 'modis.ba.poly'
UA = {'User-Agent': 'land-scout fuoco'}

# L. 353/2000 art. 10 c. 1
ANNI_DESTINAZIONE = 15      # divieto di cambio di destinazione
ANNI_EDIFICAZIONE = 10      # divieto di edificazione
SOGLIA_EFFIS_HA = 30        # sotto, il satellite puo' non vedere


class EffisNonDisponibile(RuntimeError):
    """Servizio muto: nessun esito, non 'nessun incendio'."""


def _gfi(lat, lon, da, a, d=0.004, timeout=60):
    """GetFeatureInfo in GML su TUTTA la finestra, in una sola richiesta.

    La dimensione TIME accetta un intervallo pluriennale: una chiamata per
    particella invece di una per anno (15 volte meno traffico, e verificato che
    l'esito e' identico). L'anno lo si legge da FIREDATE.
    """
    p = {'service': 'WMS', 'version': '1.1.1', 'request': 'GetFeatureInfo',
         'layers': LAYER, 'query_layers': LAYER, 'styles': '', 'srs': 'EPSG:4326',
         'bbox': f'{lon - d},{lat - d},{lon + d},{lat + d}',
         'width': '201', 'height': '201', 'x': '100', 'y': '100',
         'info_format': 'application/vnd.ogc.gml', 'feature_count': '20',
         'TIME': f'{da}-01-01/{a}-12-31'}
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            EFFIS + '?' + urllib.parse.urlencode(p), headers=UA), timeout=timeout)
        xml = r.read().decode('utf-8', 'replace')
    except Exception as e:
        raise EffisNonDisponibile(f'{type(e).__name__}: {str(e)[:60]}')
    if 'ServiceException' in xml:
        raise EffisNonDisponibile('EFFIS ha risposto con una ServiceException')

    out = []
    for blocco in xml.split('<modis.ba.poly_feature>')[1:]:
        def campo(nome):
            m = re.search(rf'<{nome}>([^<]*)</{nome}>', blocco)
            return m.group(1).strip() if m else None
        ha = campo('AREA_HA')
        agri = campo('AGRIAREAS')
        data = campo('FIREDATE')
        anno = None
        if data and len(data) >= 4 and data[:4].isdigit():
            anno = int(data[:4])
        out.append({
            'id': campo('id'), 'data': data, 'fine': campo('FINALDATE'),
            'comune': campo('COMMUNE'), 'provincia': campo('PROVINCE'),
            'area_ha': float(ha) if ha else None,
            'quota_agricola_pct': round(float(agri), 1) if agri else None,
            'anno': anno})
    return out


def storico(particelle, anni=ANNI_DESTINAZIONE, oggi=None, timeout=60, _gfi_fn=None):
    """Incendi rilevati da EFFIS sotto ciascuna particella, negli ultimi `anni`.

    Interroga il centroide anno per anno: una particella e' piccola rispetto a un
    perimetro EFFIS (soglia ~30 ha), quindi il punto basta a intercettarlo.

    Se il servizio non risponde per un anno, quell'anno resta **non verificato** e
    il conteggio lo dichiara: un buco nella serie non e' un anno senza incendi.
    """
    gfi = _gfi_fn or _gfi
    anno_fine = (oggi or date.today()).year
    anno_inizio = anno_fine - anni + 1
    anni_da_guardare = list(range(anno_inizio, anno_fine + 1))

    out, buchi = {}, set()
    for p in particelle:
        k = f"{p['fg']}_{p['pla']}"
        anello = p.get('poly') or p.get('anello')
        if anello:
            la = sum(q[0] for q in anello) / len(anello)
            lo = sum(q[1] for q in anello) / len(anello)
        else:
            la, lo = p.get('lat'), p.get('lon')
        if la is None:
            out[k] = {'verificato': False, 'incendi': [], 'percorsa_fuoco': None,
                      'ultimo_anno': None, 'anni_trascorsi': None,
                      'divieto_destinazione_fino': None, 'divieto_edificazione_fino': None,
                      'motivo': 'nessuna geometria ne coordinate'}
            continue
        ok = True
        try:
            trovati = gfi(la, lo, anno_inizio, anno_fine, timeout=timeout)
        except EffisNonDisponibile:
            trovati, ok = [], False
            buchi.update(anni_da_guardare)
        # un incendio fuori finestra non conta: il filtro TIME lo esclude gia',
        # ma se il servizio lo restituisce comunque non deve entrare nel conto
        trovati = [x for x in trovati
                   if x.get('anno') is None or anno_inizio <= x['anno'] <= anno_fine]
        recenti = sorted(trovati, key=lambda x: x.get('data') or '', reverse=True)
        ultimo = recenti[0] if recenti else None
        out[k] = {
            'verificato': ok,
            'incendi': recenti,
            'percorsa_fuoco': bool(recenti) if ok else None,
            'ultimo_anno': ultimo['anno'] if ultimo else None,
            'anni_trascorsi': (anno_fine - ultimo['anno']) if ultimo else None,
            'divieto_destinazione_fino': (ultimo['anno'] + ANNI_DESTINAZIONE) if ultimo else None,
            'divieto_edificazione_fino': (ultimo['anno'] + ANNI_EDIFICAZIONE) if ultimo else None,
        }
        if not ok and not recenti:
            out[k]['motivo'] = 'EFFIS non ha risposto per alcuni anni'

    colpite = [k for k, v in out.items() if v.get('percorsa_fuoco')]
    n_nv = sum(1 for v in out.values() if not v['verificato'])
    return {
        'particelle': out, 'anni_esaminati': anni_da_guardare,
        'n_colpite': len(colpite), 'n_totale': len(out), 'n_non_verificate': n_nv,
        'anni_non_verificati': sorted(buchi),
        'fonte': 'EFFIS / Copernicus, layer modis.ba.poly (perimetri da satellite)',
        'nota': (f'EFFIS rileva incendi da ~{SOGLIA_EFFIS_HA} ha in su: un esito negativo '
                 f'NON e un via libera. Il perimetro giuridico e quello del catasto '
                 f'incendi COMUNALE (L. 353/2000), che va comunque richiesto. Il divieto '
                 f'riguarda zone boscate e pascoli: su seminativo va valutato dal tecnico.'),
    }


def rischi(R):
    """Righe per la bancabilita' del blocco."""
    out = []
    for k, v in R['particelle'].items():
        if v.get('percorsa_fuoco'):
            u = v['incendi'][0]
            out.append(
                f"Fg{k.replace('_', '/')} percorsa dal fuoco nel {v['ultimo_anno']} "
                f"({u.get('area_ha') or '?'} ha, {u.get('comune') or ''}): L. 353/2000 "
                f"vieta il cambio di destinazione fino al {v['divieto_destinazione_fino']} "
                f"e l'edificazione fino al {v['divieto_edificazione_fino']} — "
                f"verificare il catasto incendi comunale PRIMA di ogni altra spesa")
    if R['n_non_verificate']:
        out.append(f"{R['n_non_verificate']} particelle con storico incendi NON verificato "
                   f"(EFFIS muto negli anni {R['anni_non_verificati']}): non e assenza di incendi")
    if not out:
        out.append('nessun incendio EFFIS sulle particelle negli anni esaminati: resta '
                   'da richiedere il catasto incendi comunale (soglia satellite ~30 ha)')
    return out


def applica(A, R):
    """Segna `percorsa_fuoco` sulle ammesse — campo che `engine` gia' legge come blocker.

    Non toglie la particella dal blocco qui: la decisione sta in `ammissibilita()`,
    e il divieto riguarda zone boscate e pascoli, non ogni suolo. Segnalare e far
    decidere e' il comportamento giusto quando la norma non e' meccanica.
    """
    n = 0
    for a in A['ammesse']:
        v = (R.get('particelle') or {}).get(f"{a['fg']}_{a['pla']}")
        if not v:
            continue
        a['percorsa_fuoco'] = v.get('percorsa_fuoco')
        if v.get('percorsa_fuoco'):
            a['fuoco_anno'] = v['ultimo_anno']
            a['fuoco_divieto_fino'] = v['divieto_destinazione_fino']
            n += 1
    return dict(A, fuoco={'colpite': n, 'valutate': len(R.get('particelle') or {}),
                          'non_verificate': R['n_non_verificate'], 'nota': R['nota']})


def print_report(R, top=15):
    L = [f"AREE PERCORSE DAL FUOCO — {R['n_colpite']}/{R['n_totale']} particelle "
         f"(anni {R['anni_esaminati'][0]}-{R['anni_esaminati'][-1]})"]
    mostrate = 0
    for k, v in R['particelle'].items():
        if not v.get('percorsa_fuoco') or mostrate >= top:
            continue
        mostrate += 1
        u = v['incendi'][0]
        L.append(f"  {k:<12s} {v['ultimo_anno']}  {u.get('area_ha') or '?':>7} ha  "
                 f"{(u.get('comune') or '')[:20]:<20s} divieto destinazione fino al "
                 f"{v['divieto_destinazione_fino']}")
    if R['n_non_verificate']:
        L.append(f"  ? {R['n_non_verificate']} particelle non verificate "
                 f"(anni muti: {R['anni_non_verificati']})")
    L.append('  ' + R['nota'])
    return '\n'.join(L)


def main():
    import argparse
    import json
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='Aree percorse dal fuoco (EFFIS/Copernicus).')
    ap.add_argument('--parcels', required=True,
                    help="JSON [{'fg','pla','poly'|'lat','lon'}] o un blocco.json")
    ap.add_argument('--anni', type=int, default=ANNI_DESTINAZIONE)
    ap.add_argument('--out', default=None)
    A = ap.parse_args()
    d = json.load(open(A.parcels, encoding='utf-8'))
    part = (d.get('blocco', {}).get('particelle') if isinstance(d, dict) else d) or d
    R = storico(part, anni=A.anni)
    print(print_report(R))
    for r in rischi(R):
        print('  ! ' + r)
    if A.out:
        json.dump(R, open(A.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\nscritto: {A.out}')


if __name__ == '__main__':
    main()
