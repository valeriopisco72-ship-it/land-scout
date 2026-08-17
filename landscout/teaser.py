# -*- coding: utf-8 -*-
"""land-scout teaser — la pagina che il developer legge in sessanta secondi.

Il tool produceva la mappa, il geojson, le visure, i fogli satellitari: materiale
di LAVORO. Non produceva la cosa che si manda via mail — una pagina che dica
*dove*, *quanti ettari veri*, *quanta potenza*, *a che distanza dalla rete*, *con
quante firme* e *a che prezzo*. Senza quella, ogni contatto con un developer
comincia da capo, a voce, e finisce con "mandami due righe".

## Due scelte di merito, che non sono grafiche

**1. Le lacune entrano nel teaser.** La tentazione, in un documento commerciale,
e' mostrare solo cio' che torna. Ma un developer serio la due diligence la fa: se
scopre da solo che il PAI non era stato guardato, non pensa "manca un dato",
pensa "questo materiale non e' affidabile" — e la seconda cosa costa molto piu'
della prima. Qui la sezione *"cosa resta da verificare"* e' parte del teaser, non
un allegato. E' anche l'unico modo di scriverlo restando dentro la regola di casa:
mai spacciare il non controllato per pulito.

**2. Nessun nome, mai.** Le controparti sono numeri: "12 proprietari, 3 con
opzione firmata". Nomi, codici fiscali e quote sono dati personali di terzi e non
escono dallo studio — non e' prudenza, e' che un teaser gira per mail e finisce
in cartelle che non controlli. Chi ha bisogno dei nomi ha bisogno anche di un NDA.

Uscita: **HTML autoportante** (nessuna rete, nessun font esterno). Si apre ovunque
e si stampa in PDF dal browser: Ctrl+P -> Salva come PDF. Le immagini gia' prodotte
dal blocco (forma, satellite) vengono referenziate se stanno nella stessa cartella.

Uso:
    .venv/Scripts/python -m landscout.teaser --blocco demo/_out/blocco.json \\
        [--trattativa t.json] [--out teaser.html]
"""
import html
import json
import os

VERSIONE = 'teaser v1 (10/08/2026)'


def _num(x, dec=1, suff=''):
    if x is None:
        return 'n.d.'
    if isinstance(x, (list, tuple)):
        x = [v for v in x if v is not None]
        if not x:
            return 'n.d.'
        if len(x) == 2:
            return f'{x[0]:,.{dec}f}–{x[1]:,.{dec}f}{suff}'.replace(',', '.')
        x = x[0]
    return f'{x:,.{dec}f}{suff}'.replace(',', '.')


def raccogli(d, trattativa=None):
    """Da blocco.json (+ registro) ai soli numeri che servono al teaser.

    Cio' che non c'e' resta `None` e viene stampato "n.d.": un teaser che riempie
    i buchi con valori plausibili e' esattamente il documento che non si puo'
    difendere in due diligence.
    """
    blk = d.get('blocco') or {}
    b = d.get('bancabilita') or {}
    inst = d.get('installabile') or {}
    cap = d.get('capacita_rete') or {}
    crit = (cap.get('criticita') or {})
    prezzo = d.get('prezzo') or {}
    A = d.get('ammissibilita') or {}
    C = d.get('controparti') or {}

    # controparti: SOLO numeri aggregati, mai i nomi
    n_cp = C.get('n_controparti')
    n_part = blk.get('n_acquisti')
    sotto = None
    if trattativa:
        from . import trattativa as TR
        cop = TR.copertura(trattativa)
        sotto = {'ha': cop['ha_sotto_controllo'], 'pct': cop['pct_sotto_controllo'],
                 'firme_mancanti': cop['firme_mancanti']}

    lacune = list(A.get('non_verificati') or [])
    for r in (b.get('rischi') or []):
        if 'NON verificat' in r or 'SCONOSCIUTO' in r or 'non verificat' in r:
            lacune.append(r)
    # dedup conservando l'ordine
    viste, lac = set(), []
    for x in lacune:
        if x not in viste:
            viste.add(x)
            lac.append(x)

    return {
        'comune': d.get('comune') or '',
        'titolo': blk.get('titolo') or '',
        'ha_netti': blk.get('ha_netti'),
        'ha_lordi': blk.get('ha_lordi'),
        'ha_installabili': inst.get('ha_installabile'),
        'resa_forma': inst.get('quota_installabile'),
        'mwp': b.get('mwp_stimati'),
        'n_particelle': blk.get('n'),
        'n_acquisti': n_part,
        'ha_ancore': blk.get('ha_ancore'),
        'n_controparti': n_cp,
        'sotto_controllo': sotto,
        'd_se_m': b.get('d_se_m'),
        'criticita': crit.get('livello'),
        'criticita_txt': crit.get('etichetta'),
        'prezzo_eur_ha': prezzo.get('offerta_eur_ha'),
        'prezzo_totale': prezzo.get('totale_offerto_eur'),
        'punti_forti': list(b.get('punti_forti') or []),
        'rischi': [r for r in (b.get('rischi') or []) if r not in viste],
        'lacune': lac,
        'segnalazioni': list(A.get('segnalazioni') or []),
    }


def _riga(et, val, nota=''):
    return (f'<tr><th>{html.escape(et)}</th><td>{val}</td>'
            f'<td class="n">{html.escape(nota)}</td></tr>')


def html_teaser(t, immagini=(), data=''):
    tile = [
        ('ettari netti', _num(t['ha_netti'], 1), 'al netto di vincoli, fabbricati, viabilità'),
        ('ettari installabili', _num(t['ha_installabili'], 1),
         f"resa di forma {_num((t['resa_forma'] or 0) * 100, 0, '%')}" if t['resa_forma'] else ''),
        ('MWp stimati', _num(t['mwp'], 1), 'agriPV avanzato, sugli ha installabili'),
        ('controparti', (str(t['n_controparti']) if t['n_controparti'] is not None
                         else f"≤ {t['n_acquisti']}" if t['n_acquisti'] else 'n.d.'),
         'da visura' if t['n_controparti'] is not None else 'limite superiore, senza visure'),
    ]
    tiles = ''.join(
        f'<div class="t"><div class="v">{html.escape(v)}</div>'
        f'<div class="k">{html.escape(k)}</div>'
        f'<div class="s">{html.escape(s)}</div></div>' for k, v, s in tile)

    righe = [_riga('Blocco', html.escape(t['titolo'] or '—')),
             _riga('Superficie catastale', _num(t['ha_lordi'], 2, ' ha'))]
    if t['ha_ancore']:
        righe.append(_riga('Già sotto controllo della proprietà',
                           _num(t['ha_ancore'], 2, ' ha'),
                           'non richiede acquisizione da terzi'))
    if t['sotto_controllo']:
        s = t['sotto_controllo']
        righe.append(_riga('Terra con opzione firmata',
                           f"{_num(s['ha'], 2, ' ha')} ({_num(s['pct'], 0, '%')})",
                           f"firme ancora da raccogliere: {s['firme_mancanti']}"))
    if t['d_se_m']:
        righe.append(_riga('Distanza dalla sottostazione', _num(t['d_se_m'] / 1000, 1, ' km'),
                           'misura su OSM, indicativa: il TICA lo fa il gestore'))
    if t['criticita'] is not None:
        righe.append(_riga('Criticità di rete (provincia)',
                           f"{t['criticita']}/4 — {html.escape(t['criticita_txt'] or '')}",
                           'e-Distribuzione, dato PROVINCIALE non per cabina'))
    if t['prezzo_eur_ha']:
        righe.append(_riga('Richiesta della proprietà',
                           f"{_num(t['prezzo_eur_ha'], 0, ' €/ha')}"
                           + (f" · {_num(t['prezzo_totale'], 0, ' €')} totali"
                              if t['prezzo_totale'] else '')))

    def lista(voci, cls):
        if not voci:
            return ''
        return (f'<ul class="{cls}">'
                + ''.join(f'<li>{html.escape(str(v))}</li>' for v in voci) + '</ul>')

    imgs = ''.join(
        f'<figure><img src="{html.escape(src)}" alt=""><figcaption>{html.escape(cap)}'
        f'</figcaption></figure>' for src, cap in immagini)

    return f"""<!doctype html>
<html lang="it"><meta charset="utf-8">
<title>{html.escape(t['comune'] or 'Blocco')} — scheda sintetica</title>
<style>
 @page {{ size: A4; margin: 14mm; }}
 body {{ font: 11pt/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
        color:#16110c; max-width: 900px; margin: 0 auto; padding: 18px; }}
 h1 {{ font-size: 20pt; margin: 0 0 2px; }}
 .sub {{ color:#6b6156; margin-bottom: 18px; font-size: 10pt; }}
 .tiles {{ display:flex; gap:10px; flex-wrap:wrap; margin: 0 0 18px; }}
 .t {{ flex:1 1 150px; border:1px solid #e2dbd2; border-radius:8px; padding:10px 12px; }}
 .t .v {{ font-size: 17pt; font-weight:600; }}
 .t .k {{ font-size: 9pt; text-transform:uppercase; letter-spacing:.04em; color:#6b6156; }}
 .t .s {{ font-size: 8.5pt; color:#8a8078; margin-top:3px; }}
 table {{ border-collapse: collapse; width:100%; margin-bottom:16px; }}
 th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid #efeae3;
           vertical-align:top; font-size:10pt; }}
 th {{ width: 30%; font-weight:600; color:#3d352d; }}
 td.n {{ color:#8a8078; font-size:9pt; width:32%; }}
 h2 {{ font-size:11pt; text-transform:uppercase; letter-spacing:.05em;
       color:#6b6156; margin:18px 0 6px; }}
 ul {{ margin:0 0 12px; padding-left:18px; }}
 li {{ margin-bottom:3px; font-size:10pt; }}
 ul.forti li::marker {{ content:'+ '; }}
 ul.lac li::marker {{ content:'? '; }}
 figure {{ margin:0 0 10px; }} img {{ max-width:100%; border:1px solid #e2dbd2; border-radius:6px; }}
 figcaption {{ font-size:8.5pt; color:#8a8078; }}
 .disc {{ font-size:8.5pt; color:#8a8078; border-top:1px solid #efeae3;
          padding-top:8px; margin-top:18px; }}
</style>
<h1>{html.escape(t['comune'] or 'Blocco')} — scheda sintetica</h1>
<div class="sub">{html.escape(data)} · documento preliminare, non un'offerta</div>
<div class="tiles">{tiles}</div>
<table>{''.join(righe)}</table>
{'<h2>Punti di forza</h2>' + lista(t['punti_forti'], 'forti') if t['punti_forti'] else ''}
{'<h2>Da tenere presente</h2>' + lista(t['rischi'], 'ris') if t['rischi'] else ''}
<h2>Cosa resta da verificare</h2>
{lista(t['lacune'], 'lac') if t['lacune'] else
 '<p>Nessuna verifica sospesa fra quelle che questo strumento sa eseguire.</p>'}
{imgs}
<div class="disc">
 Fonti: catasto Agenzia delle Entrate (WFS INSPIRE), Natura 2000 (EEA), IdroGEO ISPRA,
 SITAP Ministero della Cultura, Copernicus HRL, OpenStreetMap, e-Distribuzione,
 PVGIS (JRC). Le distanze di rete sono indicative: la soluzione di connessione la
 definisce il gestore (TICA). Le superfici sono catastali al netto dei vincoli
 misurati; la potenza è una stima su densità agrivoltaica avanzata.
 Nessun dato personale delle controparti è riportato in questo documento.
 Generato con land-scout · {html.escape(VERSIONE)}
</div>
</html>"""


def genera(blocco_json, out_html=None, trattativa=None, data='', immagini=None):
    """blocco.json -> teaser.html. Ritorna (path, dati)."""
    if isinstance(blocco_json, str):
        with open(blocco_json, encoding='utf-8') as f:
            d = json.load(f)
        base = os.path.dirname(os.path.abspath(blocco_json))
    else:
        d, base = blocco_json, os.getcwd()
    reg = trattativa
    if isinstance(reg, str):
        with open(reg, encoding='utf-8') as f:
            reg = json.load(f)
    t = raccogli(d, reg)

    if immagini is None:
        immagini = []
        for rel, cap in (('forma.png', 'Superficie installabile: in verde ciò che resta dopo '
                                       'il franco di rispetto'),
                         (os.path.join('satellite_da_acquisire', '_contact_sheet.png'),
                          'Verifica satellitare delle particelle da acquisire')):
            if os.path.exists(os.path.join(base, rel)):
                immagini.append((rel.replace('\\', '/'), cap))

    pagina = html_teaser(t, immagini=immagini, data=data)
    out = out_html or os.path.join(base, 'teaser.html')
    d_out = os.path.dirname(os.path.abspath(out))
    if d_out:
        os.makedirs(d_out, exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(pagina)
    return out, t


def main():
    import argparse
    import sys
    from datetime import date
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='Scheda sintetica del blocco per il developer.')
    ap.add_argument('--blocco', required=True, help='blocco.json prodotto da esporta()')
    ap.add_argument('--trattativa', default=None, help='registro trattativa (ettari sotto opzione)')
    ap.add_argument('--out', default=None)
    ap.add_argument('--data', default=None, help='data da stampare (default: oggi)')
    A = ap.parse_args()
    out, t = genera(A.blocco, A.out, trattativa=A.trattativa,
                    data=A.data or date.today().strftime('%d/%m/%Y'))
    print(f'teaser scritto: {out}')
    print(f"  {t['comune']} · {t['ha_netti']} ha netti · {t['ha_installabili']} installabili "
          f"· {len(t['lacune'])} verifiche sospese dichiarate")


if __name__ == '__main__':
    main()
