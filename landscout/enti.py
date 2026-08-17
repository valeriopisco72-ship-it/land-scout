# -*- coding: utf-8 -*-
"""land-scout enti — chi decide, e dove si presenta l'istanza.

Il tool sapeva dire *cosa* serve — VINCA, autorizzazione paesaggistica, AU — e
non ha mai saputo dire **a chi si chiede**. Sembra un dettaglio da segreteria:
non lo e'. A Morcone, il 10/08/2026, sono emersi tre fatti che cambiano il
percorso di un progetto e che nessun layer di vincolo puo' contenere:

1. **La VINCA la rilascia il COMUNE, non la Regione.** Con DD 68 dell'11.4.2022
   la Regione Campania ha delegato Morcone (L.R. 16/2014 art. 1 c. 4, come
   modificato dalla L.R. 26/2018). Cambia interlocutore, tempi e destinatario
   degli oneri istruttori (DGR 737/2022 all. A).
2. **Le VINCA gia' rilasciate dal Comune sono pubbliche.** E' il precedente piu'
   informativo che esista su un sito in ZPS: come e' andata a chi ci ha provato
   prima. Vale piu' di qualunque stima.
3. ⚠️ **Il comune e' in ZES UNICA.** Le istanze per l'**Autorizzazione Unica**
   (art. 15 D.L. 124/2023 e L. 171/2025) NON si presentano al SUAP comunale: si
   presentano allo **Sportello Unico Digitale ZES (S.U.D. ZES)**. Chi prepara un
   dossier per il SUAP sbagliato perde settimane, e lo scopre al protocollo.

Questo registro tiene insieme le tre cose per comune, con la fonte di ciascuna.
Non deduce nulla: se un comune non e' stato registrato, la risposta e' "non
verificato", mai "competenza regionale per default".

Uso:
    from landscout import enti
    print(enti.print_competenze(enti.competenze('Morcone', 'BN')))
"""
import json
import os

from .config import RAW

REGISTRO = os.path.join(str(RAW), 'enti', 'comuni.json')

# Le otto regioni della ZES unica per il Mezzogiorno (D.L. 124/2023). Serve solo
# a dire "qui va VERIFICATO", non a dedurre che un comune ci rientri: la ZES
# unica copre quelle regioni, ma la conferma sta sul portale del SUAP.
REGIONI_ZES = {'ABRUZZO', 'BASILICATA', 'CALABRIA', 'CAMPANIA', 'MOLISE',
               'PUGLIA', 'SARDEGNA', 'SICILIA'}


def _carica():
    if not os.path.exists(REGISTRO):
        return {'comuni': []}
    with open(REGISTRO, encoding='utf-8') as f:
        return json.load(f)


def _salva(d):
    os.makedirs(os.path.dirname(REGISTRO), exist_ok=True)
    with open(REGISTRO, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    return REGISTRO


def registra(comune, prov, vinca_delegata=None, vinca_atto=None, vinca_pareri_url=None,
             suap=None, zes_unica=None, zes_nota=None, fonte=None, aggiornato=None,
             gestori=None, da_verificare=None, cod_catastale=None):
    """Registra o aggiorna un comune. `fonte` obbligatoria: un dato senza
    provenienza qui vale zero, perche' le deleghe cambiano e nessuno se ne accorge.

    `gestori`: chi rilascia il "sentito" ex art. 5 c. 7 DPR 357/97, **per sito**.
    Non e' un dettaglio: nello stesso comune due particelle a tre chilometri di
    distanza possono avere due enti diversi, e a Morcone la differenza fra i due
    e' la differenza fra un imboschimento approvato e uno rigettato.
    """
    if not fonte:
        raise ValueError('senza fonte non si registra: le deleghe cambiano nel tempo')
    d = _carica()
    voce = {'comune': comune, 'prov': (prov or '').upper(),
            'vinca_delegata': vinca_delegata, 'vinca_atto': vinca_atto,
            'vinca_pareri_url': vinca_pareri_url, 'suap': suap or {},
            'zes_unica': zes_unica, 'zes_nota': zes_nota,
            'gestori': list(gestori or []),
            'da_verificare': list(da_verificare or []),
            'cod_catastale': cod_catastale,
            'fonte': fonte, 'aggiornato': aggiornato}
    d['comuni'] = [c for c in d['comuni']
                   if not (c['comune'].upper() == comune.upper()
                           and c['prov'] == (prov or '').upper())]
    d['comuni'].append(voce)
    d['comuni'].sort(key=lambda c: (c['prov'], c['comune']))
    _salva(d)
    return voce


def cerca(comune, prov=None):
    c0 = str(comune).strip().upper()
    for c in _carica()['comuni']:
        if c['comune'].upper() == c0 and (not prov or c['prov'] == prov.upper()):
            return c
    return None


def competenze(comune, prov=None, regione=None):
    """Chi decide cosa, per questo comune. Ogni voce dichiara se e' verificata."""
    c = cerca(comune, prov)
    out = {'comune': comune, 'prov': (prov or '').upper(), 'registrato': bool(c),
           'voci': [], 'avvisi': []}
    if not c:
        out['voci'].append({
            'procedura': 'VINCA', 'ente': None, 'verificato': False,
            'nota': ('comune non registrato: NON si sa se la VINCA sia delegata. '
                     'La delega si verifica sull elenco regionale dei comuni delegati, '
                     'non si deduce')})
        if (regione or '').upper() in REGIONI_ZES:
            out['avvisi'].append(
                'regione in ZES unica: verificare sul portale SUAP se il comune vi '
                'rientra — in quel caso l Autorizzazione Unica va al S.U.D. ZES')
        out['avvisi'].append('nessun dato registrato per questo comune')
        return out

    if c.get('vinca_delegata') is True:
        out['voci'].append({
            'procedura': 'VINCA', 'ente': f"Comune di {c['comune']}", 'verificato': True,
            'atto': c.get('vinca_atto'),
            'nota': ('istanza e oneri istruttori al Comune (DGR 737/2022 all. A), '
                     'non all Ufficio Speciale regionale')})
        if c.get('vinca_pareri_url'):
            out['voci'][-1]['pareri_gia_emessi'] = c['vinca_pareri_url']
    elif c.get('vinca_delegata') is False:
        out['voci'].append({
            'procedura': 'VINCA', 'ente': 'Ufficio Speciale Valutazioni Ambientali (Regione)',
            'verificato': True, 'nota': 'comune senza delega'})
    else:
        out['voci'].append({'procedura': 'VINCA', 'ente': None, 'verificato': False,
                            'nota': 'delega non verificata per questo comune'})

    if c.get('zes_unica') is True:
        out['voci'].append({
            'procedura': 'Autorizzazione Unica (FER)', 'ente': 'S.U.D. ZES',
            'verificato': True,
            'nota': (c.get('zes_nota') or
                     'comune in ZES unica: le istanze di AU (art. 15 D.L. 124/2023, '
                     'L. 171/2025) si presentano ESCLUSIVAMENTE allo Sportello Unico '
                     'Digitale ZES, non al SUAP comunale')})
        out['avvisi'].append(
            'ZES unica: prima di preparare il dossier, usare la "Comunicazione '
            'preventiva" del S.U.D. ZES per farsi dire se l istanza e di sua competenza')
    elif c.get('zes_unica') is False:
        out['voci'].append({'procedura': 'Autorizzazione Unica (FER)',
                            'ente': f"SUAP di {c['comune']}", 'verificato': True})
    else:
        out['voci'].append({'procedura': 'Autorizzazione Unica (FER)', 'ente': None,
                            'verificato': False,
                            'nota': 'ZES unica non verificata: controllare sul portale SUAP'})

    # CDU: la destinazione urbanistica non ha una fonte unica in Italia, e senza
    # non si sa se il terreno sia idoneo (il precedente RWE di Pontelandolfo del
    # 20/02/2026 regge proprio sulla zonizzazione: EO-Agricola Ordinaria + D3).
    # `cdu.py` censiva questo limite dal 14/07/2026 e NESSUNO lo chiamava: il
    # limite che era stato scritto per essere dichiarato non compariva in nessun
    # report. Stesso difetto di `ispezione`, trovato con lo stesso audit.
    if c.get('cod_catastale'):
        try:
            from .cdu import cdu_status
            s = cdu_status(c['cod_catastale'])
            out['voci'].append({
                'procedura': 'CDU (destinazione urbanistica)',
                'ente': (f"WebGIS comunale" if s['stato'] == 'webgis-manuale'
                         else f"Ufficio tecnico del Comune di {c['comune']}"),
                'verificato': s['stato'] != 'sconosciuto',
                'nota': s['nota_report']})
        except Exception:
            pass

    # vincoli che ESISTONO e che il tool NON sa controllare da solo. Vanno
    # dichiarati, non omessi: un layer che non risponde lascia una casella vuota,
    # e una casella vuota si legge come "nessun vincolo". A Morcone il caso e' il
    # perimetro del Parco Nazionale del Matese, che nessun servizio raggiungibile
    # pubblica e che sta in un allegato cartaceo a un decreto.
    out['da_verificare'] = list(c.get('da_verificare') or [])

    # il "sentito" del soggetto gestore: dipende dal SITO, non dal comune
    for g in (c.get('gestori') or []):
        out['voci'].append({
            'procedura': f"sentito art. 5 c.7 — {g.get('sito', 'sito ?')}",
            'ente': g.get('ente'), 'verificato': bool(g.get('ente')),
            'nota': g.get('nota')})
    if c.get('gestori') and len(c['gestori']) > 1:
        out['avvisi'].append(
            'in questo comune il "sentito" ha PIU di un soggetto gestore secondo il '
            'sito Natura 2000 toccato: verificare quale sito interseca la particella '
            'prima di scrivere a chi')

    if c.get('suap'):
        s = c['suap']
        out['suap'] = s
        out['voci'].append({
            'procedura': 'SUAP (altre pratiche)',
            'ente': f"SUAP n. {s.get('numero', '?')} — {s.get('indirizzo', '')}".strip(),
            'verificato': True,
            'nota': ('le istanze si inviano SOLO dal portale telematico: quelle spedite '
                     'via PEC vengono rifiutate' if s.get('solo_telematico') else None)})
    out['fonte'] = c.get('fonte')
    out['aggiornato'] = c.get('aggiornato')
    return out


def rischi(R):
    """Righe per la bancabilita': dove si sbaglia sportello si perdono settimane."""
    out = []
    for v in R['voci']:
        if v['procedura'].startswith('Autorizzazione') and (v.get('ente') or '') == 'S.U.D. ZES':
            out.append('AUTORIZZAZIONE UNICA al S.U.D. ZES, non al SUAP comunale '
                       '(comune in ZES unica): verificare la competenza con la '
                       'Comunicazione preventiva prima di preparare il dossier')
        if v['procedura'] == 'VINCA' and (v.get('ente') or '').startswith('Comune'):
            out.append(f"VINCA di competenza del {v['ente']} (delega regionale "
                       f"{v.get('atto') or ''}): istanza e oneri al Comune"
                       + (f" · pareri gia emessi: {v['pareri_gia_emessi']}"
                          if v.get('pareri_gia_emessi') else ''))
        if not v['verificato']:
            out.append(f"ente competente per {v['procedura']} NON verificato: "
                       f"{v.get('nota') or ''}")
    for d in (R.get('da_verificare') or []):
        out.append(f"DA VERIFICARE A MANO — {d.get('cosa', '?')}: "
                   f"{d.get('perche') or ''}".rstrip(': ')
                   + (f" · fonte: {d['fonte']}" if d.get('fonte') else ''))
    return out


def print_competenze(R):
    L = [f"ENTI COMPETENTI — {R['comune']} ({R['prov']})"
         + ('' if R['registrato'] else '  [NON REGISTRATO]')]
    for v in R['voci']:
        seg = '✔' if v['verificato'] else '?'
        L.append(f"  {seg} {v['procedura']:<28s} {v.get('ente') or '—'}")
        if v.get('atto'):
            L.append(f"      atto: {v['atto']}")
        if v.get('nota'):
            L.append(f"      {v['nota']}")
        if v.get('pareri_gia_emessi'):
            L.append(f"      pareri gia emessi: {v['pareri_gia_emessi']}")
    for d in (R.get('da_verificare') or []):
        L.append(f"  ? DA VERIFICARE A MANO: {d.get('cosa', '?')}")
        if d.get('perche'):
            L.append(f"      {d['perche']}")
        if d.get('fonte'):
            L.append(f"      fonte: {d['fonte']}")
    for a in R['avvisi']:
        L.append(f'  ! {a}')
    if R.get('fonte'):
        L.append(f"  fonte: {R['fonte']}" + (f" · aggiornato {R['aggiornato']}"
                                             if R.get('aggiornato') else ''))
    return '\n'.join(L)


def main():
    import argparse
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='Chi decide e dove si presenta l istanza.')
    ap.add_argument('--comune', required=True)
    ap.add_argument('--prov', default=None)
    ap.add_argument('--regione', default=None)
    ap.add_argument('--elenco', action='store_true', help='elenco dei comuni registrati')
    A = ap.parse_args()
    if A.elenco:
        for c in _carica()['comuni']:
            print(f"{c['prov']} {c['comune']:<24s} VINCA={c.get('vinca_delegata')} "
                  f"ZES={c.get('zes_unica')}")
        return
    print(print_competenze(competenze(A.comune, A.prov, A.regione)))


if __name__ == '__main__':
    main()
