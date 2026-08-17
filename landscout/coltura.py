"""land-scout coltura — che cosa c'e' DAVVERO piantato sopra, dalla visura catastale.

Il tool sapeva leggere i vincoli (ZPS, bosco 142-g, PAI, fasce) e l'occupazione
(fabbricati), ma non sapeva la cosa che il proprietario sa a memoria: **su quel
fondo c'e' un uliveto**. La quota arborea dei terreni di un caso reale
e' stata estratta a mano dalle visure e il proprietario ha
deciso di tenere oliveti e vigneti fuori dall'offerta. Quel lavoro era manuale,
non ripetibile e non applicabile ai fondi dei terzi: questo modulo lo codifica.

Perche' conta, in ordine di soldi:

1. **Un uliveto non e' terra installabile.** Espiantarlo costa, e in Campania la
   LiTAR chiede di dimostrare il mantenimento della PLV: togliere una coltura di
   pregio per metterci i pannelli e' esattamente cio' che la commissione
   agronomica guarda. Contarlo fra gli ettari "netti" e' promettere superficie
   che non esiste — lo stesso errore gia' pagato con bosco e fabbricati.

2. **Una particella mista non si scarta: si FRAZIONA.** Fg.70/654 e' 8.819 m2 di
   prato + 2.506 m2 di vigneto. Buttarla via toglie 0,88 ha buoni al blocco;
   tenerla intera regala il vigneto al compratore. La risposta giusta e' un
   frazionamento (Pregeo, 500-1.500 EUR, spesso a carico del developer).

3. **Il catasto non e' il satellite.** La qualita' catastale puo' essere vecchia
   di decenni: un "seminativo" ricolonizzato e' bosco di fatto. Questo modulo
   dice cosa c'e' scritto, non cosa si vede — i due vanno incrociati, e dove
   discordano vince il sopralluogo.

### La trappola di lettura, dichiarata

Nel PDF la tabella delle porzioni ha le qualita' su una riga sola; l'estrazione
testuale le manda a capo e l'ordine si perde quando una qualita' e' composta
("BOSCO MISTO", "SEMIN ARBOR"). Il modulo assegna le qualita' alle porzioni
**solo quando la sequenza e' univoca**; altrimenti non indovina: restituisce
l'intervallo [minimo, massimo] di superficie arborea compatibile con i dati e
marca `certo=False`. Una stima puntuale al posto di un intervallo qui vale
migliaia di euro di errore in entrambe le direzioni (su Fg.70/286 la regola
"prendi la porzione piu' grande" sbaglierebbe di 2.890 m2).

Uso:
    from landscout import coltura
    C = coltura.leggi_visura('visura_esempio.pdf')
    coltura.print_report(C)
    A2 = coltura.applica(A, C)          # A = output di blocco.ammissibilita()

CLI:
    python -m landscout.coltura --visure v1.pdf v2.pdf --out colture.json
"""
import argparse
import json
import re
from collections import Counter

try:
    from . import visure as _visure
except ImportError:  # eseguito come script sciolto
    import visure as _visure


# ---------------------------------------------------------------- vocabolario
# Qualita' catastali dei terreni, raggruppate per cio' che cambia al progetto.
# L'ordine dentro ogni tupla conta solo per la leggibilita'; il match e' per
# lunghezza decrescente (le composte prima delle semplici).
ARBOREE = (
    'ULIVETO', 'OLIVETO', 'VIGNETO', 'FRUTTETO', 'AGRUMETO', 'CASTAGNETO',
    'NOCCIOLETO', 'MANDORLETO', 'PIOPPETO', 'CANNETO', 'VIVAIO',
)
BOSCHIVE = (
    'BOSCO MISTO', 'BOSCO CEDUO', 'BOSCO ALTO', 'BOSCO DI CERRI', 'BOSCO',
    'PASCOLO CESPUGLIATO', 'CESPUGLIATO', 'INCOLTO STERILE',
)
# Miste: c'e' della legna sopra ma il fondo resta lavorabile. Non si escludono,
# si segnalano: il progettista decide se gli alberi restano fra le file.
MISTE = (
    'SEMIN ARBOR', 'SEMINATIVO ARBORATO', 'PRATO ARBORATO', 'PASCOLO ARBORATO',
    'SEM ARB IRRIG',
)
APERTE = (
    'SEMINATIVO IRRIGUO', 'SEMINATIVO', 'PRATO PASCOLO', 'PRATO IRRIGUO',
    'PRATO', 'PASCOLO', 'ORTO', 'RISAIA', 'INCOLTO PRODUTTIVO',
)
# Non agricole: la particella non entra nel gioco (e non e' un "vuoto").
DESTINAZIONI_FUORI = ('FABB DIRUTO', 'ENTE URBANO', 'AREA RURALE', 'FABBRICATO')

VOCABOLARIO = tuple(sorted(ARBOREE + BOSCHIVE + MISTE + APERTE,
                           key=len, reverse=True))

# Reddito dominicale unitario tipico (EUR/ha), solo per SUGGERIRE un
# abbinamento quando la sequenza e' ambigua. Non e' una tariffa d'estimo: e'
# l'ordine di grandezza che serve a distinguere un bosco da un seminativo.
REDDITO_TIPICO_EUR_HA = {'aperta': 30.0, 'mista': 22.0, 'arborea': 18.0, 'bosco': 5.0}


def classifica(q):
    """'aperta' | 'mista' | 'arborea' | 'bosco' | 'ignota'."""
    if not q:
        return 'ignota'
    u = re.sub(r'\s+', ' ', str(q).strip().upper())
    for v in MISTE:          # prima delle aperte: 'SEMIN ARBOR' contiene 'SEMIN'
        if u.startswith(v):
            return 'mista'
    for v in ARBOREE:
        if u.startswith(v):
            return 'arborea'
    for v in BOSCHIVE:
        if u.startswith(v):
            return 'bosco'
    for v in APERTE:
        if u.startswith(v):
            return 'aperta'
    return 'ignota'


# ---------------------------------------------------------------- 1. lettura
def _num(s):
    """'19.245' -> 19245 (il punto e' separatore di migliaia, non decimale)."""
    return int(str(s).replace('.', '').replace(' ', ''))


def _qualita_in(testo):
    """Estrae le qualita' nell'ordine in cui compaiono nel testo.

    Il testo e' la fetta fra la riga delle superfici e la riga 'Classe': ci
    stanno dentro l'etichetta 'Qualita' e i valori, spezzati a capo.
    """
    u = re.sub(r'Qualit\S*', ' ', testo.upper())
    u = re.sub(r'[^A-Z ]+', ' ', u)
    u = re.sub(r'\s+', ' ', u).strip()
    out, i = [], 0
    while i < len(u):
        for v in VOCABOLARIO:
            if u.startswith(v, i) and (i + len(v) == len(u) or u[i + len(v)] == ' '):
                out.append(v)
                i += len(v)
                break
        else:
            j = u.find(' ', i)
            i = len(u) if j < 0 else j
        i += 1
    return out


def _porzioni(blocco):
    """[(m2, classe)], qualita_set — per una particella divisa in porzioni.

    ⚠️ Le SUPERFICI e le CLASSI si leggono in colonna e sono affidabili; le
    QUALITA' no: nel PDF stanno su una riga sola e l'estrazione le manda a capo
    in un ordine che dipende da come sono andate a capo, non dalla colonna.
    Prova provata: Fg70/203 e Fg70/209 hanno testo identico
    ("SEMINATIVO / Qualita ULIVETO") e abbinamento OPPOSTO. Qui quindi si
    restituisce l'INSIEME delle qualita', mai la sequenza: l'abbinamento lo fa
    disambigua() sulle tariffe d'estimo, che sono un dato, non un'inferenza.
    """
    m = re.search(r'Superficie m2 ([\d\. ]+)', blocco)
    if not m:
        return None, []
    sup = [_num(x) for x in m.group(1).split()]
    i_cl = blocco.find('Classe', m.end())
    reg = blocco[m.end():i_cl if i_cl > 0 else m.end() + 200]
    cl = []
    if i_cl > 0:
        mc = re.match(r'Classe ([\w ]+)', blocco[i_cl:])
        if mc:
            cl = mc.group(1).split()[:len(sup)]
    cl += [None] * (len(sup) - len(cl))
    return list(zip(sup, cl)), _qualita_in(reg)


def _redditi(blocco):
    m = re.search(r'Reddito\s*\n?\s*((?:Euro [\d,\.]+\s*)+)', blocco)
    if not m:
        return []
    return [float(x.replace('.', '').replace(',', '.'))
            for x in re.findall(r'Euro ([\d,\.]+)', m.group(1))]


def leggi_visura(path, comune=None):
    """Legge una visura per soggetto (PDF) e ritorna {'fg_pla': record}.

    record = {fg, pla, m2, porzioni:[{m2, qualita, classe}], qualita_set,
              certo, fuori (destinazione non agricola), fonte}
    """
    testo = _visure._testo(path)
    out = {}
    for b in re.split(r'Immobile di catasto terreni - n\.', testo)[1:]:
        m = re.search(r'Foglio (\d+)\s+Particella (\w+)', b)
        if not m:
            continue
        fg, pla = m.group(1), m.group(2)
        if re.search(r'Subalterno', b[:m.end() + 20]):
            continue                     # catasto fabbricati, non terreni
        k = f'{fg}_{pla}'
        tot = re.search(r'Superficie:?\s*([\d\.]+) m2', b)
        m2 = _num(tot.group(1)) if tot else None

        dest = re.search(r'Particella con destinazione:\s*([A-Z ]+)', b)
        if dest and any(d in dest.group(1) for d in DESTINAZIONI_FUORI):
            out[k] = {'fg': fg, 'pla': pla, 'm2': m2, 'porzioni': [],
                      'qualita_set': [], 'certo': True, 'fuori': dest.group(1).strip(),
                      'fonte': path}
            continue

        una = re.search(r'Particella con qualit\S*:\s*([A-Z][A-Z \.]*?)\s+di classe\s*(\w+)', b)
        if una:
            q = una.group(1).strip()
            dom = re.search(r'dominicale Euro ([\d\.,]+)', b)
            out[k] = {'fg': fg, 'pla': pla, 'm2': m2,
                      'porzioni': [{'m2': m2, 'qualita': q, 'classe': una.group(2)}],
                      'qualita_set': [q], 'certo': True, 'fuori': None, 'fonte': path,
                      'redditi': ([float(dom.group(1).replace('.', '').replace(',', '.'))]
                                  if dom else [])}
            continue

        porz, qs = _porzioni(b)
        if porz:
            out[k] = {'fg': fg, 'pla': pla, 'm2': m2 or sum(s for s, _ in porz),
                      'porzioni': [{'m2': s, 'qualita': None, 'classe': c} for s, c in porz],
                      'qualita_set': qs, 'certo': False, 'fuori': None,
                      'redditi': _redditi(b), 'fonte': path}
    return out


# ---------- disambiguazione per tariffa d'estimo (non e' una stima: e' un join)
# In un comune il reddito dominicale per ettaro di una data (qualita', classe) e'
# una TARIFFA fissa. Le particelle a qualita' unica della visura la espongono in
# chiaro; le porzioni si abbinano poi per confronto. Cosi' l'ordine perduto nel
# PDF si ricostruisce da un dato presente nel documento stesso.
TOLL_TARIFFA = 0.03      # 3%: arrotondamenti a 2 decimali sugli euro
MIN_SEPARAZIONE = 0.08   # sotto: due tariffe indistinguibili, non si sceglie


def tariffe(colture):
    """{(QUALITA, classe): EUR/ha} dalle particelle a qualita' unica."""
    t = {}
    for r in colture.values():
        p = (r.get('porzioni') or [None])[0]
        if not r.get('certo') or not p or not p.get('qualita') or not r.get('m2'):
            continue
        red = (r.get('redditi') or [None])[0]
        if red is None:
            red = r.get('dominicale')
        if red:
            t.setdefault((p['qualita'].upper(), str(p.get('classe'))), []).append(
                red / (r['m2'] / 10000.0))
    return {k: round(sum(v) / len(v), 2) for k, v in t.items()}


def disambigua(rec, tar):
    """Abbina qualita' -> porzioni confrontando il reddito unitario con le tariffe.

    Assegna solo se la soluzione e' UNICA e ogni accoppiamento sta dentro la
    tolleranza. In caso contrario lascia il record ambiguo: meglio un intervallo
    dichiarato che un abbinamento inventato.
    """
    porz, red, qs = rec.get('porzioni') or [], rec.get('redditi') or [], rec.get('qualita_set') or []
    if rec.get('certo') or len(porz) < 2 or len(red) < len(porz) or len(qs) != len(porz):
        return rec
    unit = [red[i] / (porz[i]['m2'] / 10000.0) if porz[i]['m2'] else None
            for i in range(len(porz))]
    if any(u is None for u in unit):
        return rec

    # Una tariffa mancante non invalida l'abbinamento: vale come jolly. Se le
    # qualita' note si incastrano in un solo modo, quella ignota e' forzata per
    # esclusione — ed e' un'inferenza logica, non una stima. Serve pero' che
    # almeno una tariffa sia nota, altrimenti passano tutte le permutazioni e
    # il record resta (giustamente) ambiguo.
    import itertools
    ok = []
    for perm in set(itertools.permutations(qs)):
        noti = 0
        buono = True
        for i, q in enumerate(perm):
            t = tar.get((q.upper(), str(porz[i].get('classe'))))
            if t is None:
                continue
            noti += 1
            if abs(unit[i] - t) / t > TOLL_TARIFFA:
                buono = False
                break
        if buono and noti:
            ok.append(perm)
    if len(ok) != 1:
        return rec
    # due qualita' con tariffa quasi uguale non sono davvero distinguibili
    val = [tar.get((q.upper(), str(porz[i].get('classe')))) for i, q in enumerate(ok[0])]
    val = [v for v in val if v]
    if (len(set(ok[0])) > 1 and len(val) > 1
            and (max(val) - min(val)) / max(val) < MIN_SEPARAZIONE):
        return rec
    r = dict(rec, certo=True, abbinamento='tariffa d\'estimo (reddito dominicale/ha)')
    r['porzioni'] = [dict(p, qualita=q) for p, q in zip(porz, ok[0])]
    return r


def leggi_visure(paths, override=None):
    """Legge piu' visure e disambigua le porzioni con le tariffe di TUTTE.

    Leggerle insieme non e' un dettaglio: le tariffe di una qualita' che compare
    da sola solo neluna singola visura servono a sciogliere una porzione della
    visura del coniuge.

    `override` = {'fg_pla': {'arboreo_m2': int, 'fonte': str}} — quello che il
    PDF non fa dire e che si e' letto altrove (visura per immobile, sopralluogo,
    lettura a mano). Entra come dato CERTO ma con la fonte scritta accanto, cosi'
    in dossier si distingue cio' che il tool ha derivato da cio' che gli e' stato
    detto. Senza questo canale l'unica alternativa e' ricadere sul massimo
    dell'intervallo, che su Fg.70/654 butterebbe via 0,88 ha di prato buono.
    """
    out = {}
    for p in paths:
        out.update(leggi_visura(p))
    tar = tariffe(out)
    for k, r in list(out.items()):
        out[k] = disambigua(r, tar)
    for k, o in (override or {}).items():
        if k not in out or o.get('arboreo_m2') is None:
            continue
        val = int(o['arboreo_m2'])
        q0 = quota(out[k])
        if q0['certo'] and q0['m2_max'] != val:
            # l'override contraddice cio' che il tool ha DERIVATO: e' un
            # campanello, non un dettaglio. Uno dei due e' sbagliato.
            out[k] = dict(out[k], conflitto_override=(q0['m2_max'], val))
        out[k] = dict(out[k], certo=True, arboreo_m2_noto=val,
                      abbinamento=f"override: {o.get('fonte', 'lettura manuale')}")
    out['_tariffe'] = {f'{q}|cl.{c}': v for (q, c), v in sorted(tar.items())}
    return out


# ---------------------------------------------------------------- 2. quota arborea
def quota(rec, includi_bosco=False):
    """Superficie arborea della particella: valore certo o intervallo.

    includi_bosco=False perche' il bosco ha gia' il suo canale (art.142-g in
    vincoli.py): sommarlo qui lo conterebbe due volte.
    """
    cat = ('arborea',) + (('bosco',) if includi_bosco else ())
    m2 = rec.get('m2') or 0
    if rec.get('fuori'):
        return {'m2_min': 0, 'm2_max': 0, 'pct_min': 0.0, 'pct_max': 0.0,
                'certo': True, 'nota': f"destinazione {rec['fuori']}: fuori dal gioco"}

    porz = rec.get('porzioni') or []
    if rec.get('arboreo_m2_noto') is not None:
        a = rec['arboreo_m2_noto']
        pct = 100.0 * a / m2 if m2 else 0.0
        return {'m2_min': a, 'm2_max': a, 'pct_min': round(pct, 1),
                'pct_max': round(pct, 1), 'certo': True, 'nota': rec.get('abbinamento')}
    if rec.get('certo') and all(p['qualita'] for p in porz):
        a = sum(p['m2'] for p in porz if classifica(p['qualita']) in cat)
        pct = 100.0 * a / m2 if m2 else 0.0
        return {'m2_min': a, 'm2_max': a, 'pct_min': round(pct, 1),
                'pct_max': round(pct, 1), 'certo': True, 'nota': None}

    # ambigua: sappiamo QUANTE porzioni arboree ci sono, non QUALI
    sup = sorted(p['m2'] for p in porz)
    n_arb = sum(1 for q in rec.get('qualita_set', []) if classifica(q) in cat)
    if not sup or not n_arb:
        return {'m2_min': 0, 'm2_max': 0, 'pct_min': 0.0, 'pct_max': 0.0,
                'certo': bool(porz), 'nota': None if porz else 'nessun dato di qualita\''}
    lo, hi = sum(sup[:n_arb]), sum(sup[-n_arb:])
    return {'m2_min': lo, 'm2_max': hi,
            'pct_min': round(100.0 * lo / m2, 1) if m2 else 0.0,
            'pct_max': round(100.0 * hi / m2, 1) if m2 else 0.0,
            'certo': False,
            'nota': (f'{n_arb} porzione/i arborea/e su {len(sup)}, abbinamento non '
                     f'ricostruibile dal PDF: serve la visura per immobile o un sopralluogo'),
            'suggerito': _suggerisci(rec, cat)}


def _suggerisci(rec, cat):
    """Abbinamento PROBABILE per reddito unitario. Indizio, mai verdetto.

    Il reddito dominicale per ettaro separa bene un bosco (pochi EUR/ha) da un
    seminativo (decine); fra uliveto e seminativo la distanza e' piccola e il
    suggerimento vale poco. Per questo esce come campo separato e non tocca
    l'intervallo.
    """
    porz, red = rec.get('porzioni') or [], rec.get('redditi') or []
    if len(red) < len(porz) or not porz:
        return None
    qs = sorted(rec.get('qualita_set', []),
                key=lambda q: -REDDITO_TIPICO_EUR_HA.get(classifica(q), 20.0))
    if len(qs) != len(porz):
        return None
    ordine = sorted(range(len(porz)),
                    key=lambda i: -(red[i] / porz[i]['m2'] if porz[i]['m2'] else 0))
    ab = {}
    for rank, i in enumerate(ordine):
        ab[porz[i]['m2']] = qs[rank]
    return {'abbinamento': ab,
            'm2_arboreo': sum(s for s, q in ab.items() if classifica(q) in cat),
            'affidabilita': 'indizio da reddito unitario — NON verificato'}


# ---------------------------------------------------------------- 3. verdetto
SOGLIA_PULITA_PCT = 10.0    # sotto: qualche pianta sparsa, non cambia il layout
SOGLIA_ESCLUSA_PCT = 60.0   # sopra: e' un impianto arboreo, non un campo


def verdetto(rec, soglia_pulita=SOGLIA_PULITA_PCT, soglia_esclusa=SOGLIA_ESCLUSA_PCT,
             prudente=True):
    """PULITA | PARZIALE (da frazionare) | ARBOREA (fuori) | AMBIGUA | FUORI.

    prudente=True usa il massimo dell'intervallo per decidere l'esclusione: fra
    promettere ettari inesistenti e scartare un fondo buono, il primo errore
    costa credibilita' al tavolo, il secondo costa una verifica.
    """
    q = quota(rec)
    if rec.get('fuori'):
        return {'verdetto': 'FUORI', 'motivo': f"destinazione {rec['fuori']}",
                'arboreo_pct': 0.0, 'quota': q}
    pct = q['pct_max'] if prudente else q['pct_min']
    if not q['certo'] and q['pct_max'] - q['pct_min'] > soglia_pulita:
        return {'verdetto': 'AMBIGUA',
                'motivo': f"quota arborea fra {q['pct_min']}% e {q['pct_max']}%: da verificare",
                'arboreo_pct': pct, 'quota': q, 'azione': 'visura per immobile o sopralluogo'}
    if pct >= soglia_esclusa:
        return {'verdetto': 'ARBOREA', 'motivo': f'{pct:.0f}% arboreo: impianto, non campo',
                'arboreo_pct': pct, 'quota': q, 'azione': 'escludere dall\'offerta'}
    if pct <= soglia_pulita:
        return {'verdetto': 'PULITA', 'motivo': f'{pct:.0f}% arboreo', 'arboreo_pct': pct,
                'quota': q}
    return {'verdetto': 'PARZIALE', 'motivo': f'{pct:.0f}% arboreo: si offre la parte aperta',
            'arboreo_pct': pct, 'quota': q,
            'azione': f"frazionare: {q['m2_max']} m2 restano alla famiglia (Pregeo 500-1.500 EUR)"}


def valuta(colture, **kw):
    return {k: verdetto(v, **kw) for k, v in colture.items()
            if not str(k).startswith('_')}


# ---------------------------------------------------------------- 4. integrazione
def applica(A, colture, escludi_arboree=True, **kw):
    """Applica la quota arborea all'output di blocco.ammissibilita().

    - riduce `netti` della quota arborea (la parte con gli alberi non ospita moduli)
    - sposta fra gli scarti le particelle ARBOREE (se escludi_arboree)
    - lascia passare le AMBIGUE ma le marca: chi legge deve sapere che li' il
      numero non e' verificato. Una particella senza dato di coltura NON viene
      toccata — non sapere non e' una detrazione, ed e' dichiarato a parte.
    """
    V = valuta(colture, **kw)
    ammesse, scarti = [], dict(A.get('scarti') or {})
    n_ridotte = n_ambigue = 0
    ha_tolti = 0.0
    for a in A['ammesse']:
        k = f"{a['fg']}_{a['pla']}"
        v = V.get(k)
        if not v:
            a = dict(a, coltura='non verificata')
            ammesse.append(a)
            continue
        if escludi_arboree and v['verdetto'] in ('ARBOREA', 'FUORI'):
            key = 'coltura arborea (uliveto/vigneto)'
            d = scarti.setdefault(key, {'n': 0, 'ha': 0.0})
            d['n'] += 1
            d['ha'] += a['ha']
            ha_tolti += a['netti']
            continue
        pct = v['arboreo_pct'] or 0.0
        a = dict(a)
        a['coltura'] = v['verdetto']
        a['arboreo_pct'] = round(pct, 1)
        if pct > 0:
            prima = a['netti']
            a['netti'] = round(a['netti'] * (1 - pct / 100.0), 3)
            a['detrazioni'] = dict(a.get('detrazioni') or {}, arboreo_pct=round(pct, 1))
            ha_tolti += prima - a['netti']
            n_ridotte += 1
        if v['verdetto'] == 'AMBIGUA':
            n_ambigue += 1
            a['coltura_nota'] = v['motivo']
        ammesse.append(a)

    return dict(A, ammesse=ammesse, scarti=scarti,
                ha_ammessi_netti=round(sum(x['netti'] for x in ammesse), 1),
                coltura={'valutate': len(V), 'ridotte': n_ridotte, 'ambigue': n_ambigue,
                         'ha_sottratti': round(ha_tolti, 2),
                         'senza_dato': sum(1 for x in ammesse
                                           if x.get('coltura') == 'non verificata')})


# ---------------------------------------------------------------- 5. report
def print_report(colture, top=30, **kw):
    V = valuta(colture, **kw)
    c = Counter(v['verdetto'] for v in V.values())
    tot_m2 = sum((r.get('m2') or 0) for k, r in colture.items()
                 if not str(k).startswith('_'))
    arb = sum(v['quota']['m2_max'] for v in V.values())
    print('\n=== COLTURA CATASTALE ===')
    print(f"  {len(V)} particelle, {tot_m2/10000:.2f} ha; quota arborea (max) "
          f"{arb/10000:.2f} ha ({100*arb/tot_m2 if tot_m2 else 0:.1f}%)")
    for k in ('PULITA', 'PARZIALE', 'AMBIGUA', 'ARBOREA', 'FUORI'):
        if c.get(k):
            print(f"    {k:<9s} {c[k]:3d}")
    righe = [(k, v) for k, v in V.items() if v['verdetto'] in ('PARZIALE', 'ARBOREA', 'AMBIGUA')]
    righe.sort(key=lambda t: -t[1]['quota']['m2_max'])
    if righe:
        print('  da decidere (arboreo decrescente):')
        for k, v in righe[:top]:
            q = v['quota']
            r = colture[k]
            qs = '+'.join(dict.fromkeys(r.get('qualita_set') or [])) or 'n.d.'
            span = (f"{q['m2_min']}-{q['m2_max']}" if not q['certo'] else f"{q['m2_max']}")
            print(f"    Fg{r['fg']}/{r['pla']:<6s} {r.get('m2',0):>7,d} m2  "
                  f"arboreo {span:>13s} m2  {v['verdetto']:<8s} [{qs}]")
    amb = [k for k, v in V.items() if v['verdetto'] == 'AMBIGUA']
    if amb:
        print(f"  [!] {len(amb)} particelle con abbinamento qualita'->porzione non "
              f"ricostruibile: NON sono 'pulite', sono 'non lette' -> {', '.join(amb)}")
    if colture.get('_tariffe'):
        print(f"  tariffe d'estimo ricostruite dalla visura stessa: "
              f"{len(colture['_tariffe'])} coppie (qualita', classe)")
    return V


def main():
    ap = argparse.ArgumentParser(description='Quota arborea (uliveti/vigneti) dalle visure')
    ap.add_argument('--visure', nargs='+', required=True)
    ap.add_argument('--out')
    ap.add_argument('--override', help='JSON {"fg_pla": {"arboreo_m2": n}} da lettura manuale')
    ap.add_argument('--includi-bosco', action='store_true')
    a = ap.parse_args()
    ov = None
    if a.override:
        with open(a.override, encoding='utf-8') as f:
            ov = json.load(f)
    C = leggi_visure(a.visure, override=ov)
    V = print_report(C)
    conf = {k: r['conflitto_override'] for k, r in C.items()
            if isinstance(r, dict) and r.get('conflitto_override')}
    if conf:
        print('  [!] OVERRIDE IN CONFLITTO col dato derivato (derivato, override):')
        for k, v in conf.items():
            print(f'      {k}: {v[0]} vs {v[1]} m2')
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as f:
            json.dump({'colture': C, 'verdetti': V}, f, ensure_ascii=False, indent=1)
        print('scritto', a.out)


if __name__ == '__main__':
    main()
