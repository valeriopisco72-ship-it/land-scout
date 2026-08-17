# -*- coding: utf-8 -*-
"""land-scout trattativa — lo stato dell'aggregazione, fra un run e l'altro.

Tutto il resto del tool fotografa un istante: vincoli, ettari, prezzo. Ma un
blocco non si compra in un pomeriggio — si compra in 12-24 mesi, parlando con
15-30 persone, e la domanda che conta ogni lunedi' mattina non e' "quanto vale
il terreno" ma **"a che punto sono, e chi devo richiamare questa settimana"**.

Finora quella risposta viveva nella testa di chi tratta. Il che significa tre
cose, tutte viste in trattative vere:
  1. **le opzioni scadono senza che nessuno se ne accorga** — ed e' l'unico
     errore di questo mestiere che non si puo' rimediare: il proprietario che
     ha firmato e non e' stato richiamato in tempo, la volta dopo non firma;
  2. si ricontatta due volte chi ha gia' detto no e si dimentica chi era tiepido;
  3. non si sa mai **quanto blocco e' davvero sotto controllo** — e senza quel
     numero non si puo' dire a un developer "ne ho 20 di ettari", si puo' solo
     sperarlo.

## Cosa NON fa

Non decide niente e non manda niente. E' un registro: lo aggiorni tu dopo ogni
telefonata. Un CRM che prova a indovinare lo stato dai silenzi produce lo stesso
danno di un layer che scambia l'assenza di dato per assenza di vincolo — e qui
l'assenza di dato ha un nome: **una riga non aggiornata da 45 giorni non e' una
trattativa che procede, e' una trattativa di cui non sai niente.** Il modulo lo
dice, non lo nasconde.

## Perche' gli ettari "sotto controllo" contano solo con l'opzione firmata

Un "sono interessato" al telefono vale zero in una due diligence. Qui la
copertura si calcola **solo** su `opzione` e `rogito`: sono gli unici due stati
in cui, se il developer chiede "fammi vedere", hai un foglio da mostrare.

Uso:
    .venv/Scripts/python -m landscout.trattativa --apri demo/blocco.json --out t.json
    .venv/Scripts/python -m landscout.trattativa --reg t.json --stato "ROSSI MARIO=opzione" \\
        --scadenza 2026-12-31 --ore 3 --nota "firmata opzione 6 mesi"
    .venv/Scripts/python -m landscout.trattativa --reg t.json            # riepilogo
"""
import argparse
import json
import os
from datetime import date, datetime, timedelta

# Ordine = avanzamento. Serve a due cose: ordinare il riepilogo e capire se uno
# stato e' andato AVANTI o INDIETRO (un 'rifiutato' dopo un'opzione e' una notizia).
STATI = ['da_contattare', 'contattato', 'interessato', 'in_trattativa',
         'opzione', 'rogito', 'rifiutato', 'irreperibile']
# Solo questi valgono come terra che puoi mostrare a un developer.
STATI_CONTROLLO = ('opzione', 'rogito')
# Questi tolgono la particella dal blocco finche' non cambia qualcosa.
STATI_PERSI = ('rifiutato', 'irreperibile')

GIORNI_STANTIO = 45          # oltre, la riga non e' "in corso": e' ignota
GIORNI_PREAVVISO = 30        # finestra di allerta sulle scadenze

# L'altro lato del tavolo. Un blocco si vende a un developer, e anche quel
# percorso ha stati, date e una scadenza che fa danno se passa inosservata:
# **l'esclusiva**. Chi la concede e se ne dimentica scopre di aver bloccato il
# proprio terreno per sei mesi in cambio di niente.
STATI_DEV = ['da_contattare', 'contattato', 'nda', 'in_valutazione',
             'offerta_ricevuta', 'accordo', 'rifiutato', 'fermo']


class StatoIgnoto(ValueError):
    """Uno stato fuori dall'elenco: meglio fermarsi che scrivere un valore a caso."""


def _oggi(oggi=None):
    if oggi is None:
        return date.today()
    if isinstance(oggi, date):
        return oggi
    return datetime.strptime(str(oggi)[:10], '%Y-%m-%d').date()


def _data(v):
    if not v:
        return None
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def apri(blocco, controparti=None, oggi=None, comune=''):
    """Crea il registro dal blocco (e dalle visure, se ci sono).

    Senza visure le righe sono le PARTICELLE: si sa quanto offrire, non a chi —
    ed e' scritto nel registro, cosi' nessuno lo dimentica leggendo i totali.
    """
    g = _oggi(oggi).isoformat()
    righe = []
    ancore = {(str(p['fg']), str(p['pla'])) for p in blocco['particelle'] if p.get('ancora')}
    if controparti and controparti.get('controparti'):
        per = 'proprietario'
        for c in controparti['controparti']:
            det = [d for d in (c.get('dettaglio') or [])
                   if (str(d['fg']), str(d['pla'])) not in ancore]
            ha = (sum(d['ha_quota'] for d in det) if c.get('dettaglio')
                  else c.get('ha_controllati') or 0)
            if ha <= 0:
                continue                      # possiede solo terra gia' tua
            righe.append({'chi': c['nome'], 'ha': round(ha, 3),
                          'particelle': [f"{d['fg']}/{d['pla']}" for d in det],
                          'solo_diritti_deboli': c.get('solo_diritti_deboli'),
                          'stato': 'da_contattare', 'aggiornato': g,
                          'scadenza': None, 'ore': 0.0, 'note': []})
    else:
        per = 'particella (visure mancanti: non si sa a CHI si sta parlando)'
        for p in blocco['particelle']:
            if p.get('ancora'):
                continue
            righe.append({'chi': f"Fg{p['fg']}/{p['pla']}", 'ha': round(p['netti'], 3),
                          'particelle': [f"{p['fg']}/{p['pla']}"],
                          'solo_diritti_deboli': None,
                          'stato': 'da_contattare', 'aggiornato': g,
                          'scadenza': None, 'ore': 0.0, 'note': []})
    righe.sort(key=lambda r: -r['ha'])
    return {'comune': comune, 'titolo': blocco.get('titolo', ''), 'per': per,
            'aperto': g, 'ha_target': round(sum(r['ha'] for r in righe), 2),
            'ha_ancore': blocco.get('ha_ancore', 0.0), 'righe': righe,
            'developer': []}


def carica(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def salva(reg, path):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    return path


def _riga(reg, chi):
    chi_n = str(chi).strip().upper()
    for r in reg['righe']:
        if r['chi'].strip().upper() == chi_n:
            return r
    # match parziale: in trattativa si scrive "Rossi", non l'intestazione completa
    cand = [r for r in reg['righe'] if chi_n in r['chi'].strip().upper()]
    if len(cand) == 1:
        return cand[0]
    if len(cand) > 1:
        raise ValueError(f"'{chi}' corrisponde a {len(cand)} controparti: "
                         + ', '.join(c['chi'] for c in cand[:4]))
    raise ValueError(f"'{chi}' non e' nel registro")


def aggiorna(reg, chi, stato=None, nota=None, scadenza=None, ore=None, oggi=None):
    """Aggiorna una riga. Ogni modifica lascia una nota datata: senza storia, un
    registro e' solo l'ultima cosa che ti ricordi."""
    r = _riga(reg, chi)
    g = _oggi(oggi).isoformat()
    if stato is not None:
        if stato not in STATI:
            raise StatoIgnoto(f"stato '{stato}' sconosciuto: usa uno fra {', '.join(STATI)}")
        prima = r['stato']
        r['stato'] = stato
        if stato != prima:
            r['note'].append({'data': g, 'testo': f'{prima} -> {stato}'})
    if scadenza is not None:
        if _data(scadenza) is None:
            raise ValueError(f"scadenza '{scadenza}' non e' una data YYYY-MM-DD")
        r['scadenza'] = _data(scadenza).isoformat()
    if ore:
        r['ore'] = round((r.get('ore') or 0) + float(ore), 2)
    if nota:
        r['note'].append({'data': g, 'testo': nota})
    r['aggiornato'] = g
    return r


def developer(reg, nome, stato=None, nda=None, esclusiva_fino=None, nota=None,
              contatto=None, oggi=None):
    """L'altro lato del tavolo: chi sta guardando questo blocco, e con che vincoli.

    `match.py` dice CHI chiamare (aziende con progetti VIA vicini). Qui si tiene
    il conto di chi e' stato davvero contattato, se c'e' un NDA e — la voce che
    fa danno se passa inosservata — **fino a quando vale un'esclusiva**: chi la
    concede e se ne dimentica ha bloccato il proprio terreno per mesi in cambio
    di niente.
    """
    g = _oggi(oggi).isoformat()
    reg.setdefault('developer', [])
    d = next((x for x in reg['developer']
              if x['nome'].strip().upper() == str(nome).strip().upper()), None)
    if d is None:
        d = {'nome': str(nome).strip(), 'stato': 'da_contattare', 'nda': False,
             'esclusiva_fino': None, 'contatto': None, 'aggiornato': g, 'note': []}
        reg['developer'].append(d)
    if stato is not None:
        if stato not in STATI_DEV:
            raise StatoIgnoto(f"stato developer '{stato}' sconosciuto: usa uno fra "
                              + ', '.join(STATI_DEV))
        if stato != d['stato']:
            d['note'].append({'data': g, 'testo': f"{d['stato']} -> {stato}"})
        d['stato'] = stato
    if nda is not None:
        d['nda'] = bool(nda)
    if contatto is not None:
        d['contatto'] = contatto
    if esclusiva_fino is not None:
        if _data(esclusiva_fino) is None:
            raise ValueError(f"esclusiva '{esclusiva_fino}' non e' una data YYYY-MM-DD")
        d['esclusiva_fino'] = _data(esclusiva_fino).isoformat()
    if nota:
        d['note'].append({'data': g, 'testo': nota})
    d['aggiornato'] = g
    return d


def copertura(reg):
    """Quanti ettari sono DAVVERO sotto controllo, e cosa resta da prendere.

    Il rischio ostaggio si ricalcola su chi MANCA: una controparte che pesava il
    16% del blocco, una volta firmata, non e' piu' un rischio — e chi resta pesa
    di piu' di prima. E' il numero che cambia l'ordine delle telefonate.
    """
    tot = sum(r['ha'] for r in reg['righe']) or 0.0
    sotto = sum(r['ha'] for r in reg['righe'] if r['stato'] in STATI_CONTROLLO)
    persi = sum(r['ha'] for r in reg['righe'] if r['stato'] in STATI_PERSI)
    aperti = [r for r in reg['righe']
              if r['stato'] not in STATI_CONTROLLO + STATI_PERSI]
    ha_aperti = sum(r['ha'] for r in aperti)
    pivot = []
    for r in aperti:
        # peso sul RESIDUO da prendere, non sul blocco intero
        q = 100 * r['ha'] / ha_aperti if ha_aperti else 0
        if q >= 15:
            pivot.append({'chi': r['chi'], 'ha': r['ha'], 'quota_residuo_pct': round(q, 1),
                          'stato': r['stato']})
    return {'ha_totali': round(tot, 2), 'ha_sotto_controllo': round(sotto, 2),
            'pct_sotto_controllo': round(100 * sotto / tot, 1) if tot else 0.0,
            'ha_persi': round(persi, 2), 'ha_aperti': round(ha_aperti, 2),
            'firme_mancanti': len(aperti),
            'pivotali_residui': sorted(pivot, key=lambda x: -x['ha']),
            'nota': ('sotto controllo = solo opzione firmata o rogito. Un "sono '
                     'interessato" al telefono non e un ettaro che puoi mostrare.')}


def scadenze(reg, entro_giorni=GIORNI_PREAVVISO, oggi=None):
    """Opzioni ED esclusive in scadenza (e gia' scadute).

    Le due date hanno versi opposti — una la ricevi, l'altra la concedi — ma
    l'errore e' identico e ugualmente irrimediabile: accorgersene dopo.
    """
    g = _oggi(oggi)
    out = []
    for r in reg['righe']:
        d = _data(r.get('scadenza'))
        if not d:
            continue
        gg = (d - g).days
        if gg <= entro_giorni:
            out.append({'tipo': 'opzione', 'chi': r['chi'], 'ha': r['ha'],
                        'stato': r['stato'], 'scadenza': d.isoformat(),
                        'giorni': gg, 'scaduta': gg < 0})
    for x in (reg.get('developer') or []):
        d = _data(x.get('esclusiva_fino'))
        if not d:
            continue
        gg = (d - g).days
        if gg <= entro_giorni:
            out.append({'tipo': 'esclusiva', 'chi': x['nome'], 'ha': None,
                        'stato': x['stato'], 'scadenza': d.isoformat(),
                        'giorni': gg, 'scaduta': gg < 0})
    return sorted(out, key=lambda x: x['giorni'])


def stantii(reg, giorni=GIORNI_STANTIO, oggi=None):
    """Righe ferme da troppo. Non sono "in corso": sono ignote, e vanno dette."""
    g = _oggi(oggi)
    out = []
    for r in reg['righe']:
        if r['stato'] in STATI_CONTROLLO + STATI_PERSI:
            continue
        d = _data(r.get('aggiornato'))
        if d and (g - d).days >= giorni:
            out.append({'chi': r['chi'], 'ha': r['ha'], 'stato': r['stato'],
                        'fermo_da_giorni': (g - d).days})
    return sorted(out, key=lambda x: -x['fermo_da_giorni'])


def economia(reg, fee_eur=None, fee_eur_ha=None):
    """Quanto vale il TUO lavoro su questo blocco, non quanto vale la terra.

    Il tool sa dire quanto offrire al proprietario. Non ha mai detto quanto costa
    a te procurare quella firma — ed e' il conto che serve per decidere se un
    blocco vale il tempo che chiede, o se le stesse ore rendono di piu' altrove.
    La fee la dichiari tu: qui non si inventa un prezzo di mercato che non esiste.
    """
    ore = sum((r.get('ore') or 0) for r in reg['righe'])
    cop = copertura(reg)
    fee = None
    if fee_eur is not None:
        fee = float(fee_eur)
    elif fee_eur_ha is not None:
        fee = float(fee_eur_ha) * cop['ha_totali']
    return {'ore_spese': round(ore, 1),
            'ore_per_firma': (round(ore / max(1, sum(1 for r in reg['righe']
                                                     if r['stato'] in STATI_CONTROLLO)), 1)
                              if any(r['stato'] in STATI_CONTROLLO for r in reg['righe'])
                              else None),
            'fee_attesa_eur': round(fee) if fee is not None else None,
            'eur_ora_se_chiude': (round(fee / ore) if fee is not None and ore else None),
            'eur_ora_a_oggi': (round(fee * cop['pct_sotto_controllo'] / 100 / ore)
                               if fee is not None and ore else None),
            'nota': ('la fee la dichiari tu (--fee o --fee-ha): non esiste un prezzo di '
                     'mercato pubblico per il site hunting, e inventarne uno qui '
                     'renderebbe finto anche il resto del conto.')}


def portafoglio(percorsi, oggi=None, fee_eur_ha=None):
    """Tutti i blocchi in lavorazione, in una riga sola.

    `trattativa` guarda un blocco alla volta; questo guarda il mestiere. Serve a
    rispondere alla domanda del lunedi' mattina — *dove sono messo davvero* — e
    a quella che viene dopo: **queste ore rendono piu' qui o altrove?**
    Accetta una cartella o un elenco di file: un registro illeggibile viene
    dichiarato, non saltato in silenzio.
    """
    if isinstance(percorsi, str):
        percorsi = ([os.path.join(percorsi, f) for f in sorted(os.listdir(percorsi))
                     if f.endswith('.json')] if os.path.isdir(percorsi) else [percorsi])
    blocchi, illeggibili = [], []
    for p in percorsi:
        try:
            reg = carica(p)
            if 'righe' not in reg:
                raise ValueError('non e un registro trattativa')
        except Exception as e:
            illeggibili.append({'file': os.path.basename(p), 'errore': f'{type(e).__name__}'})
            continue
        c = copertura(reg)
        sc = scadenze(reg, oggi=oggi)
        st = stantii(reg, oggi=oggi)
        blocchi.append({
            'file': os.path.basename(p), 'comune': reg.get('comune') or '',
            'titolo': reg.get('titolo') or '',
            'ha_totali': c['ha_totali'], 'ha_sotto_controllo': c['ha_sotto_controllo'],
            'pct': c['pct_sotto_controllo'], 'firme_mancanti': c['firme_mancanti'],
            'ore': round(sum((r.get('ore') or 0) for r in reg['righe']), 1),
            'scadenze_30gg': len(sc), 'scadute': sum(1 for x in sc if x['scaduta']),
            'righe_ferme': len(st),
            'developer_attivi': sum(1 for d in (reg.get('developer') or [])
                                    if d['stato'] not in ('rifiutato', 'fermo',
                                                          'da_contattare')),
        })
    blocchi.sort(key=lambda b: -b['ha_sotto_controllo'])
    ore = sum(b['ore'] for b in blocchi)
    ha_c = sum(b['ha_sotto_controllo'] for b in blocchi)
    ha_t = sum(b['ha_totali'] for b in blocchi)
    val = (fee_eur_ha * ha_c) if fee_eur_ha else None
    return {'blocchi': blocchi, 'n_blocchi': len(blocchi),
            'ha_totali': round(ha_t, 2), 'ha_sotto_controllo': round(ha_c, 2),
            'pct': round(100 * ha_c / ha_t, 1) if ha_t else 0.0,
            'ore_totali': round(ore, 1),
            'scadenze_30gg': sum(b['scadenze_30gg'] for b in blocchi),
            'scadute': sum(b['scadute'] for b in blocchi),
            'valore_maturato_eur': round(val) if val is not None else None,
            'eur_ora': (round(val / ore) if val is not None and ore else None),
            'illeggibili': illeggibili,
            'nota': ('il valore e maturato SOLO sugli ettari con opzione firmata: '
                     'il resto e pipeline, non portafoglio.')}


def print_portafoglio(P):
    L = [f"PORTAFOGLIO — {P['n_blocchi']} blocchi · {P['ha_sotto_controllo']} / "
         f"{P['ha_totali']} ha sotto controllo ({P['pct']}%) · {P['ore_totali']} ore"]
    if P['valore_maturato_eur'] is not None:
        L.append(f"  valore maturato {P['valore_maturato_eur']:,} EUR "
                 f"· {P['eur_ora']} EUR/ora".replace(',', '.'))
    if P['scadute']:
        L.append(f"  ! {P['scadute']} scadenze GIA PASSATE")
    if P['scadenze_30gg']:
        L.append(f"  ! {P['scadenze_30gg']} scadenze entro 30 giorni")
    L.append(f"  {'comune':<16s} {'ha ctrl':>8s} {'ha tot':>7s} {'%':>5s} {'firme':>6s} "
             f"{'ore':>5s} {'dev':>4s}")
    for b in P['blocchi']:
        L.append(f"  {(b['comune'] or b['file'])[:16]:<16s} {b['ha_sotto_controllo']:8.2f} "
                 f"{b['ha_totali']:7.2f} {b['pct']:5.0f} {b['firme_mancanti']:6d} "
                 f"{b['ore']:5.1f} {b['developer_attivi']:4d}"
                 + ('  ! ferme: %d' % b['righe_ferme'] if b['righe_ferme'] else ''))
    for x in P['illeggibili']:
        L.append(f"  ? {x['file']}: {x['errore']} — registro non letto, non contato")
    L.append('  ' + P['nota'])
    return '\n'.join(L)


def print_stato(reg, oggi=None, fee_eur=None, fee_eur_ha=None):
    L = [f"TRATTATIVA — {reg.get('comune') or ''} {reg.get('titolo', '')}".rstrip(),
         f"  righe per: {reg['per']}"]
    cop = copertura(reg)
    L.append(f"  SOTTO CONTROLLO {cop['ha_sotto_controllo']} / {cop['ha_totali']} ha "
             f"({cop['pct_sotto_controllo']}%) · da prendere {cop['ha_aperti']} ha "
             f"con {cop['firme_mancanti']} firme"
             + (f" · persi {cop['ha_persi']} ha" if cop['ha_persi'] else ''))
    sc = scadenze(reg, oggi=oggi)
    for s in sc:
        ha = f"{s['ha']:6.2f} ha" if s.get('ha') is not None else '          '
        L.append(f"  {'SCADUTA' if s['scaduta'] else 'SCADE'} fra {s['giorni']:>4} gg  "
                 f"[{s.get('tipo', 'opzione')}] {s['chi'][:26]:<26s} {ha}  ({s['scadenza']})")
    st = stantii(reg, oggi=oggi)
    for s in st:
        L.append(f"  fermo da {s['fermo_da_giorni']:>3} gg   {s['chi'][:34]:<34s} "
                 f"{s['ha']:6.2f} ha  [{s['stato']}]")
    L.append('  ---')
    for r in sorted(reg['righe'], key=lambda x: (STATI.index(x['stato']), -x['ha'])):
        L.append(f"  {r['stato']:<14s} {r['chi'][:34]:<34s} {r['ha']:6.2f} ha  "
                 f"agg. {r['aggiornato']}" + (f"  scad. {r['scadenza']}" if r.get('scadenza') else ''))
    for p in cop['pivotali_residui']:
        L.append(f"  ! PIVOTALE ancora aperta: {p['chi']} — {p['quota_residuo_pct']}% "
                 f"di cio che manca")
    if st:
        L.append(f"  ! {len(st)} righe ferme da oltre {GIORNI_STANTIO} giorni: non sono "
                 f"trattative in corso, sono trattative di cui non sai niente")
    for d in (reg.get('developer') or []):
        L.append(f"  developer      {d['nome'][:30]:<30s} [{d['stato']}]"
                 + ('  NDA' if d.get('nda') else '')
                 + (f"  esclusiva fino {d['esclusiva_fino']}" if d.get('esclusiva_fino') else ''))
    ec = economia(reg, fee_eur=fee_eur, fee_eur_ha=fee_eur_ha)
    if ec['ore_spese']:
        L.append(f"  ore spese {ec['ore_spese']}"
                 + (f" · fee attesa {ec['fee_attesa_eur']:,} EUR"
                    f" · {ec['eur_ora_se_chiude']} EUR/ora se chiude"
                    if ec['fee_attesa_eur'] else ''))
    return '\n'.join(L)


def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Stato della trattativa su un blocco.")
    ap.add_argument('--apri', help='blocco.json prodotto da blocco.esporta()')
    ap.add_argument('--controparti', help='controparti.json (da visure): righe per PERSONA')
    ap.add_argument('--reg', help='registro esistente da leggere/aggiornare')
    ap.add_argument('--out', help='dove salvare (default: sovrascrive --reg)')
    ap.add_argument('--stato', help='"NOME=stato" (' + ' | '.join(STATI) + ')')
    ap.add_argument('--nota', help='"NOME=testo" oppure solo testo se usato con --stato')
    ap.add_argument('--scadenza', help='YYYY-MM-DD, scadenza dell opzione')
    ap.add_argument('--ore', type=float, help='ore da aggiungere alla riga')
    ap.add_argument('--fee', type=float, help='fee attesa in EUR (per il conto del tuo lavoro)')
    ap.add_argument('--fee-ha', type=float, dest='fee_ha', help='fee attesa in EUR/ha')
    ap.add_argument('--dev', help='"DEVELOPER=stato" (' + ' | '.join(STATI_DEV) + ')')
    ap.add_argument('--nda', action='store_true', help='con --dev: NDA firmato')
    ap.add_argument('--esclusiva', help='con --dev: data di scadenza YYYY-MM-DD')
    ap.add_argument('--portafoglio', help='cartella di registri: la vista su TUTTI i blocchi')
    A = ap.parse_args()

    if A.portafoglio:
        P = portafoglio(A.portafoglio, fee_eur_ha=A.fee_ha)
        print(print_portafoglio(P))
        return
    if A.dev:
        if not A.reg:
            raise SystemExit('--dev richiede --reg')
        reg = carica(A.reg)
        nome, _, st = A.dev.partition('=')
        developer(reg, nome, stato=(st.strip() or None), nda=(True if A.nda else None),
                  esclusiva_fino=A.esclusiva, nota=A.nota)
        salva(reg, A.out or A.reg)
        print(print_stato(reg, fee_eur=A.fee, fee_eur_ha=A.fee_ha))
        return

    if A.apri:
        d = json.load(open(A.apri, encoding='utf-8'))
        blk = d.get('blocco') or d
        C = json.load(open(A.controparti, encoding='utf-8')) if A.controparti else None
        reg = apri(blk, C, comune=d.get('comune', ''))
        out = A.out or A.reg or 'trattativa.json'
        salva(reg, out)
        print(f'registro aperto: {len(reg["righe"])} righe -> {out}')
        print(print_stato(reg))
        return
    if not A.reg:
        raise SystemExit('serve --apri (per creare) oppure --reg (per leggere/aggiornare)')
    reg = carica(A.reg)
    if A.stato:
        chi, _, st = A.stato.partition('=')
        nota = A.nota
        if nota and '=' in nota and nota.split('=')[0].strip().upper() == chi.strip().upper():
            nota = nota.split('=', 1)[1]
        aggiorna(reg, chi, stato=st.strip() or None, nota=nota,
                 scadenza=A.scadenza, ore=A.ore)
        salva(reg, A.out or A.reg)
    elif A.nota or A.scadenza or A.ore:
        chi, _, testo = (A.nota or '').partition('=')
        aggiorna(reg, chi, nota=testo or None, scadenza=A.scadenza, ore=A.ore)
        salva(reg, A.out or A.reg)
    print(print_stato(reg, fee_eur=A.fee, fee_eur_ha=A.fee_ha))


if __name__ == '__main__':
    main()
