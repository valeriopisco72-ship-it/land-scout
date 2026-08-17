"""land-scout visure — da 30 particelle a "quante famiglie devo convincere".

Il collo di bottiglia dell'aggregatore non e' trovare la terra: e' sapere **con
chi si tratta**. Il tool sa dire "30 particelle da acquisire", ma 30 particelle
non sono 30 controparti — possono essere 7 famiglie con piu' fondi a testa, e
questo cambia completamente la fattibilita' del deal.

COSA FA E COSA NON FA
---------------------
Fa: legge le visure catastali che **tu hai gia' scaricato** dalla tua area
riservata e le trasforma in una mappa delle controparti — chi possiede cosa,
con che quota, chi ha di fatto un potere di veto, da chi conviene partire.

NON fa: non entra al posto tuo nell'area riservata dell'Agenzia delle Entrate.
Automatizzare quell'accesso vorrebbe dire gestire le tue credenziali SPID (cosa
che non faccio), quasi certamente violare le condizioni d'uso del portale, e
scontrarsi con i controlli anti-bot. Il download resta un tuo gesto autenticato.
E' anche il pezzo veloce: sono ~10 minuti di clic. Il pezzo lento — leggere 30
PDF e capire chi conta — e' quello che questo modulo toglie di mezzo.

DATI PERSONALI
--------------
Le visure contengono nome, data e luogo di nascita e codice fiscale di terzi.
Sono dati che ottieni lecitamente dal catasto per una finalita' legittima
(verificare la proprieta' dei fondi che vuoi aggregare), ma restano dati
personali: `aggrega()` produce di default un output **senza CF** per l'uso
quotidiano, e li tiene solo in `dettaglio` per quando servono davvero (atti,
notaio). Non vanno in teaser, mappe o file condivisi.

Uso:
    from landscout import visure
    V = visure.leggi_cartella('visure_scaricate/')
    C = visure.aggrega(V, blocco=blk)
    visure.print_controparti(C)
"""
import glob
import json
import os
import re
import unicodedata
from collections import defaultdict

# "1. ROSSI Mario (CF RSSMRA70A01F717X) Nato a MORCONE (BN) il 01/01/1970
#     Diritto di: Proprieta' per 1000/1000"
RE_INTEST = re.compile(
    r'^\s*(\d+)\.\s+(.+?)\s*\(CF\s*([A-Z0-9]{11,16})\)\s*(.*?)$', re.M)
RE_NATO = re.compile(r'Nat[oa]\s+a\s+(.+?)\s+\((\w{2})\)\s+il\s+(\d{2}/\d{2}/\d{4})')
RE_SEDE = re.compile(r'sede\s+in\s+([A-ZÀ-Ù\' ]+)', re.I)
RE_DIRITTO = re.compile(r"Diritto di:\s*(.+?)\s+per\s+(\d+)\s*/\s*(\d+)", re.S)
RE_IMMOBILE = re.compile(r'Immobile di catasto (terreni|fabbricati)\s*-\s*n\.\s*(\d+)')
RE_COMUNE = re.compile(r'Comune di\s+(.+?)\s*\(\s*([A-Z]\d{3})\s*\)')
RE_FGPLA = re.compile(r'Foglio\s+(\d+)\s+Particella\s+(\d+)')
RE_SUP = re.compile(r'Superficie:\s*([\d.]+)\s*m2')

# Diritti DOMINICALI: si spartiscono la titolarita' del fondo, e le loro quote
# sommano all'intero. E' su questi che si ripartiscono gli ettari.
DIRITTI_DOMINICALI = ('PROPRIETA', "PROPRIETA'", 'NUDA PROPRIETA', "NUDA PROPRIETA'",
                      'ENFITEUSI', 'CONCEDENTE', 'SUPERFICIAR', 'LIVELLO')
# Diritti di GODIMENTO: gravano sul fondo senza esserne titolarita'. Chi li ha
# NON possiede ettari, ma per un contratto trentennale il suo consenso serve
# lo stesso: resta controparte, con zero ettari.
DIRITTI_GODIMENTO = ('USUFRUTTO', 'USO', 'ABITAZIONE', 'SERVITU')


def _classe_diritto(d):
    d = (d or '').upper()
    if any(x in d for x in DIRITTI_GODIMENTO) and not any(
            x in d for x in ('NUDA PROPRIETA', "NUDA PROPRIETA'")):
        return 'godimento'
    if any(x in d for x in DIRITTI_DOMINICALI):
        return 'dominicale'
    return 'ignoto'


def _norm(s):
    """Nome confrontabile: niente accenti, spazi doppi, maiuscole."""
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', s).strip().upper()


def _testo(path):
    if path.lower().endswith('.pdf'):
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return '\n'.join((p.extract_text() or '') for p in pdf.pages)
    return open(path, encoding='utf-8', errors='replace').read()


def _intestatari(sez):
    """Righe intestatario di una sezione 'Intestazione attuale'."""
    out = []
    for m in RE_INTEST.finditer(sez):
        resto = m.group(4)
        coda = sez[m.end():m.end() + 200]      # il diritto spesso va a capo
        md = RE_DIRITTO.search(resto + ' ' + coda)
        mn = RE_NATO.search(resto + ' ' + coda)
        out.append({
            'nome': _norm(m.group(2)),
            'cf': m.group(3),
            'diritto': (md.group(1).strip().upper() if md else None),
            'quota': (f'{md.group(2)}/{md.group(3)}' if md else None),
            'quota_frazione': (int(md.group(2)) / int(md.group(3))
                               if md and int(md.group(3)) else None),
            'nato_a': (mn.group(1).strip() if mn else None),
            'nato_il': (mn.group(3) if mn else None),
            'persona_giuridica': bool(RE_SEDE.search(resto)),
        })
    return out


def leggi(path):
    """Estrae gli immobili e i loro intestatari da una visura (PDF o testo).

    Funziona sia sulle visure *per soggetto* sia su quelle *per immobile*.

    ⚠️ Il punto delicato: quando piu' immobili hanno la stessa intestazione, la
    visura NON la ripete — scrive **"Intestazione attuale degli immobili dal
    n. 5 al n. 7"** una volta sola. Attribuirla al solo blocco in cui compare
    lascia gli altri senza proprietario, e un proprietario che sparisce fa
    sottostimare le controparti: l'errore va nella direzione peggiore. Per
    questo qui si indicizza per NUMERO d'immobile e si assegna a tutto
    l'intervallo.
    """
    txt = _testo(path)

    # 1) gli immobili, con il loro numero progressivo
    tagli = [(m.start(), m.group(1), int(m.group(2))) for m in RE_IMMOBILE.finditer(txt)]
    imm = {}
    ordine = []
    for i, (a, tipo, num) in enumerate(tagli):
        b = tagli[i + 1][0] if i + 1 < len(tagli) else len(txt)
        blocco = txt[a:b]
        mf = RE_FGPLA.search(blocco)
        if not mf:
            continue
        mc = RE_COMUNE.search(blocco)
        ms = RE_SUP.search(blocco)
        imm[num] = {
            'n': num, 'tipo': tipo,
            'comune': (mc.group(1).strip() if mc else None),
            'cod_comune': (mc.group(2) if mc else None),
            'fg': mf.group(1), 'pla': mf.group(2),
            'mq': (int(ms.group(1).replace('.', '')) if ms else None),
            'intestatari': [], 'fonte': os.path.basename(path),
        }
        ordine.append(num)

    # 2) le intestazioni, singole o su intervallo, assegnate per numero
    RE_HEAD = re.compile(
        r"Intestazione attuale (?:dell'immobile n\.\s*(\d+)"
        r"|degli immobili dal n\.\s*(\d+)\s*al n\.\s*(\d+))")
    teste = [(m.start(), m) for m in RE_HEAD.finditer(txt)]
    for i, (a, m) in enumerate(teste):
        b = teste[i + 1][0] if i + 1 < len(teste) else len(txt)
        # la sezione si ferma anche al prossimo immobile, se viene prima
        for s, _, _ in tagli:
            if a < s < b:
                b = s
                break
        righe = _intestatari(txt[a:b])
        if m.group(1):
            nums = [int(m.group(1))]
        else:
            nums = list(range(int(m.group(2)), int(m.group(3)) + 1))
        for n in nums:
            if n in imm:
                imm[n]['intestatari'] = righe

    return [imm[n] for n in ordine]


def leggi_cartella(d, pattern='*.pdf'):
    out = []
    for f in sorted(glob.glob(os.path.join(d, pattern))):
        try:
            out.extend(leggi(f))
        except Exception as e:
            print(f'  ATTENZIONE: {os.path.basename(f)} non letto ({type(e).__name__})')
    return out


def aggrega(visure, blocco=None, solo_terreni=True, con_cf=False):
    """Da un elenco di immobili a una mappa delle CONTROPARTI.

    Se passi `blocco`, considera solo le particelle che ne fanno parte e pesa
    ciascun proprietario per gli **ettari netti** che controlla — non per il
    numero di particelle, che e' la misura sbagliata: chi ha una particella da
    3 ha conta piu' di chi ne ha quattro da 0,2.

    L'identita' e' il **codice fiscale**, non il nome: gli omonimi in un comune
    piccolo sono la norma, e due 'ROSSI Mario' diversi che diventano uno solo
    falsano tutto il conteggio delle controparti.
    """
    idx = {}
    if blocco:
        for p in blocco['particelle']:
            idx[(str(p['fg']), str(p['pla']))] = p

    prop = defaultdict(lambda: {'nome': None, 'cf': None, 'particelle': [],
                                'ha': 0.0, 'persona_giuridica': False,
                                'solo_diritti_deboli': True})
    fuori, senza_intest = [], []

    # DEDUPLICA: una particella cointestata compare in TUTTE le visure dei suoi
    # comproprietari. Su Morcone i fondi in comproprieta fra coniugi arrivavano
    # due volte e gonfiavano il totale di 1,12 ha. Si tiene la versione con piu'
    # intestatari, che e' quella completa.
    uniche = {}
    for im in visure:
        k = (im.get('cod_comune'), str(im['fg']), str(im['pla']), im['tipo'])
        pre = uniche.get(k)
        if pre is None or len(im['intestatari']) > len(pre['intestatari']):
            uniche[k] = im
    n_dup = len(visure) - len(uniche)

    for im in uniche.values():
        if solo_terreni and im['tipo'] != 'terreni':
            continue
        k = (str(im['fg']), str(im['pla']))
        p = idx.get(k)
        if blocco and p is None:
            fuori.append(k)
            continue
        ha_tot = (p or {}).get('netti')
        if ha_tot is None:
            ha_tot = (im['mq'] or 0) / 10000.0
        if not im['intestatari']:
            senza_intest.append(k)
            continue

        # Su una stessa particella coesistono diritti DIVERSI (nuda proprieta' +
        # usufrutto, concedente + enfiteusi): le loro quote sommano a piu' di 1.
        # Sommarle tutte gonfierebbe gli ettari — su una visura reale portava il
        # totale da 9,24 a 10,89 ha. Gli ettari si ripartiscono solo fra i
        # diritti dominicali, normalizzati per sommare esattamente alla particella.
        dom = [t for t in im['intestatari'] if _classe_diritto(t['diritto']) == 'dominicale']
        if not dom:                      # nessun dominicale riconosciuto: non si inventa
            dom = [t for t in im['intestatari'] if _classe_diritto(t['diritto']) == 'ignoto']
        s_dom = sum((t['quota_frazione'] or 0) for t in dom) or 1.0

        for t in im['intestatari']:
            cls = _classe_diritto(t['diritto'])
            d = prop[t['cf']]
            d['nome'] = d['nome'] or t['nome']
            d['cf'] = t['cf']
            d['persona_giuridica'] = d['persona_giuridica'] or t['persona_giuridica']
            if cls != 'godimento':
                d['solo_diritti_deboli'] = False
            q = (t['quota_frazione'] or 0) / s_dom if t in dom else 0.0
            d['ha'] += ha_tot * q
            d['particelle'].append({'fg': k[0], 'pla': k[1], 'quota': t['quota'],
                                    'diritto': t['diritto'], 'classe': cls,
                                    'ha_quota': round(ha_tot * q, 3)})

    # Enfiteusi / livello: il fondo ha due titolari, concedente e enfiteuta.
    # Non e' un dettaglio contabile — e' un tema di TITOLO, come gli usi civici:
    # per vendere o concedere per trent'anni o si coinvolge il concedente o si
    # affranca. Va detto, non spalmato in silenzio sulle quote.
    titoli = []
    for im in uniche.values():
        if solo_terreni and im['tipo'] != 'terreni':
            continue
        k = (str(im['fg']), str(im['pla']))
        if blocco and k not in idx:
            continue
        d_all = ' '.join((t['diritto'] or '') for t in im['intestatari'])
        if 'ENFITEUSI' in d_all or 'CONCEDENTE' in d_all or 'LIVELLO' in d_all:
            titoli.append({
                'fg': k[0], 'pla': k[1], 'tipo': 'enfiteusi/livello',
                'soggetti': [{'nome': t['nome'], 'diritto': t['diritto']}
                             for t in im['intestatari']],
                'nota': 'due titolari (concedente + enfiteuta): per vendere o '
                        'concedere serve il concedente, oppure affrancare',
            })

    tot_ha = sum(d['ha'] for d in prop.values()) or 1.0
    lista = []
    for cf, d in prop.items():
        lista.append({
            'nome': d['nome'],
            'cf': (cf if con_cf else None),
            'n_particelle': len(d['particelle']),
            'ha_controllati': round(d['ha'], 3),
            'quota_blocco_pct': round(100 * d['ha'] / tot_ha, 1),
            'persona_giuridica': d['persona_giuridica'],
            'solo_diritti_deboli': d['solo_diritti_deboli'],
            'dettaglio': d['particelle'],
        })
    lista.sort(key=lambda x: -x['ha_controllati'])

    # da quante firme dipende l'80% degli ettari
    cum, n80 = 0.0, 0
    for x in lista:
        cum += x['ha_controllati']
        n80 += 1
        if cum >= 0.8 * tot_ha:
            break

    n_att = len(idx) if blocco else len({(v['fg'], v['pla']) for v in visure})
    coperte = {(str(v['fg']), str(v['pla'])) for v in uniche.values()
               if not solo_terreni or v['tipo'] == 'terreni'}
    mancanti = sorted(set(idx) - coperte) if blocco else []

    return {
        'controparti': lista,
        'n_controparti': len(lista),
        'ha_totali': round(tot_ha, 2),
        'controparti_per_80pct': n80,
        'quota_max_pct': lista[0]['quota_blocco_pct'] if lista else 0.0,
        'particelle_coperte': len(coperte & set(idx)) if blocco else len(coperte),
        'particelle_attese': n_att,
        'particelle_mancanti': mancanti,
        'particelle_fuori_blocco': sorted(set(fuori)),
        'senza_intestatari': sorted(set(senza_intest)),
        'immobili_duplicati_uniti': n_dup,
        'titoli_da_sanare': titoli,
        'completo': (not mancanti) if blocco else None,
    }


def print_controparti(C, top=15):
    stato = ('COMPLETO' if C.get('completo') else
             f"PARZIALE: mancano {len(C['particelle_mancanti'])} particelle su "
             f"{C['particelle_attese']}")
    print(f"\n=== CONTROPARTI REALI ({stato}) ===")
    print(f"  {C['n_controparti']} proprietari distinti su {C['particelle_coperte']} particelle "
          f"({C['ha_totali']} ha)")
    print(f"  l'80% degli ettari dipende da {C['controparti_per_80pct']} firme")
    print(f"  {'nome':<34s} {'part':>4s} {'ha':>7s} {'%blocco':>8s}")
    for x in C['controparti'][:top]:
        note = []
        if x['persona_giuridica']:
            note.append('societa')
        if x['solo_diritti_deboli']:
            note.append('solo usufrutto/uso')
        print(f"  {(x['nome'] or '?')[:34]:<34s} {x['n_particelle']:>4d} "
              f"{x['ha_controllati']:>7.2f} {x['quota_blocco_pct']:>7.1f}%"
              + (('  [' + ', '.join(note) + ']') if note else ''))
    if C['particelle_mancanti']:
        print(f"  ancora da chiedere: "
              + ', '.join(f'Fg{a}/{b}' for a, b in C['particelle_mancanti'][:12]))
    if C.get('titoli_da_sanare'):
        print(f"  TITOLO da chiarire su {len(C['titoli_da_sanare'])} particelle:")
        for x in C['titoli_da_sanare'][:6]:
            chi = ' + '.join(f"{a['nome'].split()[0]} ({a['diritto']})" for a in x['soggetti'])
            print(f"    Fg{x['fg']}/{x['pla']}  {x['tipo']}: {chi.replace(chr(10),' ')}")
        print(f"    ~ {C['titoli_da_sanare'][0]['nota']}")
    if C['senza_intestatari']:
        print(f"  ATTENZIONE, visure senza intestatari leggibili: "
              + ', '.join(f'Fg{a}/{b}' for a, b in C['senza_intestatari'][:8]))


def applica_a_bancabilita(b, C):
    """Sostituisce il conteggio per PARTICELLA con quello per PROPRIETARIO.

    Finche' le visure mancano, `bancabilita()` conta le particelle e lo dichiara
    come limite superiore. Qui quel limite diventa il numero vero, e il rischio
    ostaggio si ricalcola sulla quota di chi possiede — che e' la domanda giusta:
    non "quanto pesa questa particella" ma "quanto pesa questa firma".
    """
    if not C or not C['controparti']:
        return b
    b = dict(b)
    b['n_controparti_reali'] = C['n_controparti']
    b['controparti_per_80pct'] = C['controparti_per_80pct']
    b['nota_controparti'] = (f"{C['n_controparti']} proprietari REALI da visura "
                             f"(prima si contavano {b.get('n_acquisti')} particelle)"
                             + ('' if C.get('completo') else
                                f" — copertura PARZIALE: {len(C['particelle_mancanti'])} "
                                f"particelle ancora da verificare"))
    b['rischi'] = [r for r in b.get('rischi', []) if 'controparti' not in r]
    if C['quota_max_pct'] >= 15:
        top = C['controparti'][0]
        b['rischi'].append(
            f"rischio ostaggio REALE: {top['nome']} controlla il {top['quota_max_pct'] if False else C['quota_max_pct']:.0f}% "
            f"del blocco ({top['ha_controllati']} ha in {top['n_particelle']} particelle) — "
            f"senza la sua firma il progetto non si fa")
    if C['controparti_per_80pct'] <= 5:
        b.setdefault('punti_forti', []).append(
            f"concentrazione favorevole: l'80% degli ettari dipende da "
            f"{C['controparti_per_80pct']} firme")
    if C.get('titoli_da_sanare'):
        b['rischi'].append(
            f"titolo da chiarire su {len(C['titoli_da_sanare'])} particelle "
            f"(enfiteusi/livello): serve il concedente o l'affrancazione")
    if not C.get('completo'):
        b['rischi'].append(
            f"quadro proprietario INCOMPLETO: {len(C['particelle_mancanti'])} particelle "
            f"senza visura, il numero di controparti puo' solo salire")
    return b
