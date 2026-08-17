# -*- coding: utf-8 -*-
"""land-scout precedenti — come e' andata a chi ci ha provato prima, qui.

Il tool sa leggere i layer: dove passa il vincolo, quanto e' ripida la
particella, quanto dista la cabina. Non ha mai saputo leggere la cosa che un
developer chiede per prima quando gli porti un sito dentro una ZPS: *e' mai
stato autorizzato qualcosa, qui?* Un layer dice cosa e' vietato in astratto;
un fascicolo di VIncA gia' decise dice cosa passa davvero, con quali
prescrizioni, in quanti giorni e chi firma.

A Morcone (fascicolo 2022-2026, 46 pratiche) la differenza fra le due cose e'
stata netta e verificabile:

  · lo stesso intervento — imboschire un terreno agricolo — e' stato
    **approvato** nella ZPS del Tammaro (CUP 30) e **rigettato per divieto
    assoluto** nella ZSC del Monte Mutria (CUP 31). Il discrimine non era il
    progetto: era l'habitat (6210) e il soggetto gestore (il Parco, non la
    Regione).
  · sei tagli di bosco su sei sono passati, due sui fogli dove sta la terra di
    famiglia, con prescrizioni identiche e ricorrenti.

Da qui la regola di questo modulo: **niente deduzioni**. Se per un comune non
e' stato letto nessun fascicolo, la risposta e' "non lo so", mai "nessun
ostacolo". E un precedente favorevole su un intervento DIVERSO non e' un
precedente favorevole: viene riportato come tale, separato.

Uso:
    from landscout import precedenti as PR
    R = PR.contro_blocco(blk, 'Morcone', 'BN')
    print(PR.print_precedenti(R))
"""
import json
import os
import re

from .config import RAW

REGISTRO_DIR = os.path.join(str(RAW), 'precedenti')

# le famiglie di intervento che ha senso distinguere quando si cerca un
# precedente. L'ordine conta: la prima che matcha vince come tipo principale.
TIPI = (
    ('fer', r'fotovoltaic\w*\s+(?:a\s+terra|di\s+potenza)|agrivoltaic|impiant[oi]\s+eolic'
            r'|impiant[oi]\s+di\s+accumulo|\bBESS\b|utility[\s-]scale'),
    ('taglio_bosco', r'taglio\s+(?:di\s+)?bosc|taglio\s+delle\s+piante|diradament'
                     r'|utilizzazion\w*\s+forestal'),
    ('imboschimento', r'imboschiment|rimboschiment|arboricoltura\s+da\s+legno'),
    ('recinzione', r'recinzion'),
    ('edilizia', r'fabbricat|ristruttur|demolizion|ricostruzion|accertamento\s+di\s+conformit'),
    ('viabilita', r'\bstrad\w+|viabilit|pista|dissest'),
    ('reti', r'acquedott|condott|metanodott|fognar|elettrodott'),
    ('agricolo', r'\bPSR\b|\bCSR\b|invaso|serra|stalla|zootec|oliv|vign'),
)

ESITI = ('FAVOREVOLE', 'FAVOREVOLE CON PRESCRIZIONI', 'NEGATIVO', 'NON CONCLUSA')


def _file(comune, prov):
    return os.path.join(REGISTRO_DIR, f"{str(comune).strip().lower()}_"
                                      f"{str(prov or '').strip().lower()}.json")


def _carica(comune, prov):
    p = _file(comune, prov)
    if not os.path.exists(p):
        return None
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def classifica(testo):
    """Le famiglie di intervento citate in un testo, in ordine di specificita'."""
    t = testo or ''
    return [n for n, rx in TIPI if re.search(rx, t, re.I)]


def registra(comune, prov, voci, fonte=None, aggiornato=None):
    """Scrive il registro dei precedenti di un comune.

    `voci`: lista di dict con almeno {cup, oggetto, esito}. `fonte` obbligatoria:
    un precedente senza il documento da cui viene non e' un precedente, e'
    un ricordo.
    """
    if not fonte:
        raise ValueError('senza fonte non si registra un precedente')
    pulite = []
    for v in voci:
        if not v.get('cup'):
            raise ValueError('ogni voce deve avere un identificativo (cup)')
        e = (v.get('esito') or 'NON CONCLUSA').upper()
        if e not in ESITI:
            raise ValueError(f'esito non ammesso: {e} (ammessi: {", ".join(ESITI)})')
        pulite.append({
            'cup': v['cup'], 'proponente': v.get('proponente'),
            'oggetto': v.get('oggetto') or '',
            'tipo': list(v.get('tipo') or classifica(v.get('oggetto') or '')),
            'citati': list(v.get('citati') or []),
            'sito': v.get('sito'), 'gestore': v.get('gestore'),
            'procedura': v.get('procedura'), 'esito': e,
            'motivo': v.get('motivo'),
            'particelle': [[str(f), str(p)] for f, p in (v.get('particelle') or [])],
            'ha': v.get('ha'), 'data': v.get('data'),
            'giorni_istruttoria': v.get('giorni_istruttoria'),
            'prescrizioni': list(v.get('prescrizioni') or []),
            'documento': v.get('documento')})
    d = {'comune': comune, 'prov': (prov or '').upper(), 'fonte': fonte,
         'aggiornato': aggiornato, 'voci': pulite}
    os.makedirs(REGISTRO_DIR, exist_ok=True)
    with open(_file(comune, prov), 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    return d


def cerca(comune, prov, tipo=None, esito=None, fg=None):
    d = _carica(comune, prov)
    if not d:
        return []
    out = d['voci']
    if tipo:
        out = [v for v in out if tipo in (v.get('tipo') or [])]
    if esito:
        out = [v for v in out if v['esito'] == esito.upper()]
    if fg is not None:
        fg = str(fg)
        out = [v for v in out if any(f == fg for f, _ in v['particelle'])]
    return out


def _fogli_e_particelle(blk):
    """Fogli e particelle di un blocco, in qualunque forma sia arrivato."""
    P = blk.get('particelle') if isinstance(blk, dict) else None
    if P is None and isinstance(blk, dict):
        P = (blk.get('blocco') or {}).get('particelle')
    P = P or []
    part = {(str(p.get('fg')), str(p.get('pla'))) for p in P
            if p.get('fg') is not None and p.get('pla') is not None}
    return {f for f, _ in part}, part


def contro_blocco(blk, comune, prov, tipo='fer'):
    """Incrocia un blocco col registro: cosa e' gia' stato deciso, qui.

    Restituisce tre livelli, che NON vanno confusi fra loro:
      · `esatti`        — decisioni sulle STESSE particelle del blocco;
      · `stesso_foglio` — decisioni sugli stessi fogli: contesto, non precedente;
      · `per_tipo`      — come e' andata, per famiglia di intervento, in tutto
                          il comune.
    """
    R = {'comune': comune, 'prov': (prov or '').upper(), 'letto': False,
         'esatti': [], 'stesso_foglio': [], 'per_tipo': {}, 'negativi': [],
         'prescrizioni_ricorrenti': [], 'avvisi': [], 'fonte': None,
         'tipo_cercato': tipo}
    d = _carica(comune, prov)
    if not d:
        R['avvisi'].append(
            f'nessun fascicolo di precedenti letto per {comune}: NON si sa se in '
            f'questo comune sia mai stato autorizzato qualcosa di simile. '
            f'I pareri gia rilasciati sono pubblici — vanno scaricati e registrati')
        return R
    R['letto'] = True
    R['fonte'] = d.get('fonte')
    R['aggiornato'] = d.get('aggiornato')
    fogli, part = _fogli_e_particelle(blk)

    for v in d['voci']:
        pv = {(f, p) for f, p in v['particelle']}
        if pv & part:
            R['esatti'].append({**v, 'match': sorted(pv & part)})
        elif {f for f, _ in pv} & fogli:
            R['stesso_foglio'].append({**v, 'fogli': sorted({f for f, _ in pv} & fogli)})

    for v in d['voci']:
        for t in (v.get('tipo') or ['(non classificata)']):
            s = R['per_tipo'].setdefault(t, {'n': 0, 'favorevoli': 0, 'negativi': 0})
            s['n'] += 1
            if v['esito'].startswith('FAVOREVOLE'):
                s['favorevoli'] += 1
            elif v['esito'] == 'NEGATIVO':
                s['negativi'] += 1
        if v['esito'] == 'NEGATIVO':
            R['negativi'].append(v)

    # le prescrizioni che tornano in piu' pareri: sono quelle che il progetto
    # deve gia' contenere per non farsi rimandare indietro.
    conta = {}
    for v in d['voci']:
        for p in set(v.get('prescrizioni') or []):
            conta[p] = conta.get(p, 0) + 1
    R['prescrizioni_ricorrenti'] = [p for p, n in sorted(conta.items(), key=lambda x: -x[1])
                                    if n >= 2]

    st = R['per_tipo'].get(tipo)
    if not st:
        R['avvisi'].append(
            f'nel fascicolo NON c e nessuna pratica di tipo "{tipo}": significa che '
            f'nessuno ci ha ancora provato, non che sia ammesso. Il primo che presenta '
            f'istruisce anche la commissione')
    elif st['negativi']:
        R['avvisi'].append(
            f'{st["negativi"]} pratica/e di tipo "{tipo}" gia RIGETTATA in questo comune: '
            f'leggere la motivazione prima di impostare il progetto')
    return R


def rischi(R):
    """Righe per la bancabilita'. Un precedente negativo pesa piu' di un layer."""
    out = []
    if not R.get('letto'):
        out.extend(R.get('avvisi') or [])
        return out
    for v in R.get('negativi') or []:
        out.append(f"PRECEDENTE NEGATIVO nello stesso comune — {v['cup']}: "
                   f"{(v.get('motivo') or v.get('oggetto') or '')[:160]}"
                   + (f" (gestore: {v['gestore']})" if v.get('gestore') else ''))
    for v in R.get('esatti') or []:
        out.append(f"su particelle del blocco esiste gia una decisione — {v['cup']} "
                   f"({v['esito']}): {', '.join('/'.join(m) for m in v['match'][:6])}"
                   f" · {(v.get('oggetto') or '')[:90]}")
    st = (R.get('per_tipo') or {}).get(R.get('tipo_cercato'))
    if st and st['n'] and not st['negativi']:
        out.append(f"precedenti favorevoli di tipo \"{R['tipo_cercato']}\" in questo comune: "
                   f"{st['favorevoli']}/{st['n']} — utile in relazione di incidenza")
    out.extend(a for a in (R.get('avvisi') or []) if a not in out)
    return out


def print_precedenti(R, max_righe=8):
    L = [f"PRECEDENTI VIncA — {R['comune']} ({R['prov']})"
         + ('' if R['letto'] else '  [FASCICOLO NON LETTO]')]
    if R['letto']:
        for t, s in sorted(R['per_tipo'].items(), key=lambda x: -x[1]['n']):
            seg = '✔' if s['favorevoli'] and not s['negativi'] else (
                '✖' if s['negativi'] and not s['favorevoli'] else '·')
            L.append(f"  {seg} {t:<16s} {s['favorevoli']}/{s['n']} favorevoli"
                     + (f"  ({s['negativi']} rigettate)" if s['negativi'] else ''))
        if R['esatti']:
            L.append('  particelle del blocco gia interessate da una decisione:')
            for v in R['esatti'][:max_righe]:
                L.append(f"    {v['cup']:<6s} {v['esito']:<12s} "
                         f"{', '.join('/'.join(m) for m in v['match'][:6])}")
        if R['stesso_foglio']:
            L.append(f"  stesso foglio (contesto, non precedente): "
                     + ', '.join(f"{v['cup']}(fg {'/'.join(v['fogli'])})"
                                 for v in R['stesso_foglio'][:max_righe]))
        if R['prescrizioni_ricorrenti']:
            L.append('  prescrizioni ricorrenti — mettere gia in progetto:')
            for p in R['prescrizioni_ricorrenti'][:max_righe]:
                L.append(f'    · {p}')
        if R.get('fonte'):
            L.append(f"  fonte: {R['fonte']}"
                     + (f" · aggiornato {R['aggiornato']}" if R.get('aggiornato') else ''))
    for a in R['avvisi']:
        L.append(f'  ! {a}')
    return '\n'.join(L)


# --------------------------------------------------------------------------
# lettura di un fascicolo scaricato (cartella di PDF)
# --------------------------------------------------------------------------

def _testo_pdf(path):
    import fitz
    with fitz.open(path) as d:
        return re.sub(r'\s+', ' ', ' '.join(p.get_text() for p in d))


def _numeri(seg):
    """I numeri di particella dentro un elenco, senza i codici che gli stanno
    accanto. Nei documenti l'elenco confina con la sigla dell'ufficio
    ('...449 - 721 - 189 - 329 213-02-02 UOS Tutela...'): senza questo taglio
    il codice dell'ufficio diventa una particella, e la particella finta poi
    sembra un precedente."""
    m = re.search(r'\d{1,4}-\d{2}-\d{2}', seg)
    if m:
        seg = seg[:m.start()]
    return [p for p in re.findall(r'\d{1,4}', seg[:80])
            if not (len(p) > 1 and p[0] == '0')]


def particelle_citate(t):
    """(foglio, particella) citati in un testo di determina o parere."""
    out = set()
    for m in re.finditer(
            r'p(?:articell|\.ll)[ae]\s*(?:n\.?|nn\.?)?\s*([\d,\s\-–eE]+?)\s*'
            r'del\s*(?:f(?:ogli)?o?\.?)\s*(\d{1,3})', t, re.I):
        for p in _numeri(m.group(1)):
            out.add((m.group(2), p))
    for m in re.finditer(
            r'f(?:ogli)?o\.?\s*(?:n\.?)?\s*(\d{1,3})[,\s]+p(?:ar)?[.\w]*\s*'
            r'(?:n\.?)?\s*([\d,\s\-–]+)', t, re.I):
        for p in _numeri(m.group(2)):
            out.add((m.group(1), p))
    return sorted(out, key=lambda x: (int(x[0]), int(x[1])))


# Il divieto stagionale delle utilizzazioni forestali si scrive con le stesse
# parole di un rigetto ("divieto assoluto ... nel periodo 1 aprile-31 luglio").
# Leggere l'esito su tutto il fascicolo trasforma quindi un parere FAVOREVOLE
# con prescrizioni nel suo contrario: e' successo su CUP 30, 41, 42 e 46 alla
# prima stesura di questo modulo. L'esito si legge SOLO nel dispositivo.
RX_NEG = re.compile(
    r'CONCLUSION[EI]\s+NEGATIVA|RIGETTO\s+E\s+ARCHIVIAZIONE|ESITO\s+NEGATIVO'
    r'|SENTITO\s+NON\s+FAVOREVOLE|parere\s+negativo\s+di\s+valutazione'
    r'|DIVIETO\s+ASSOLUTO\s+DI\s+ATTIVIT', re.I)
RX_POS = re.compile(
    r'PARERE\s+FAVOREVOLE|NULLA\s+OSTA|SENTITO\s+FAVOREVOLE'
    r'|ESCLUDERE\s+il\s+propost|non\s+determiner[àa]\s+incidenz', re.I)
RX_DISPOSITIVO = re.compile(
    r'DETERMINAZIONE\s+DEL\s+RESPONSABILE|D\s*E\s*T\s*E\s*R\s*M\s*I\s*N\s*A\b'
    r'|DETERMINA\s*(?:N|n)?[\.\s]*\d', re.I)


def esito_da_dispositivo(testo_determina):
    """L'esito di una pratica, letto nel dispositivo. Se non c'e' dispositivo,
    l'esito NON si desume dal parere: resta 'NON CONCLUSA'."""
    t = testo_determina or ''
    if not t.strip():
        return 'NON CONCLUSA'
    # il dispositivo comincia a "DETERMINA": prima ci sono i "visto" e i "premesso"
    m = re.search(r'D\s*E\s*T\s*E\s*R\s*M\s*I\s*N\s*A\b', t)
    disp = t[m.start():] if m else t
    if RX_NEG.search(disp):
        return 'NEGATIVO'
    if RX_POS.search(disp):
        return ('FAVOREVOLE CON PRESCRIZIONI'
                if re.search(r'PRESCRIZION', disp, re.I) else 'FAVOREVOLE')
    return 'NON CONCLUSA'


def leggi_fascicolo(cartella, comune, prov, siti=None, fonte=None, salva=True):
    """Legge una cartella di pratiche (una sottocartella per pratica) e ne
    ricava il registro. Non inventa: cio' che non riesce a leggere resta
    dichiarato in `non_letti`, e ogni voce porta il file da cui viene."""
    siti = siti or {}
    fasc, non_letti = {}, []
    for radice, _dirs, files in os.walk(cartella):
        for f in files:
            if not f.lower().endswith('.pdf'):
                continue
            chiave = os.path.basename(radice) or os.path.basename(cartella)
            fasc.setdefault(chiave, []).append(os.path.join(radice, f))

    voci = []
    for chiave in sorted(fasc):
        testi = []
        for p in sorted(fasc[chiave]):
            try:
                t = _testo_pdf(p)
            except Exception as e:
                non_letti.append({'file': p, 'errore': f'{type(e).__name__}: {e}'[:120]})
                continue
            if len(t) < 200:
                non_letti.append({'file': p, 'errore': 'testo assente (scansione senza OCR)'})
                continue
            testi.append((p, t))
        if not testi:
            non_letti.append({'file': chiave, 'errore': 'nessun documento leggibile'})
            continue
        intero = ' '.join(t for _, t in testi)
        # il dispositivo si riconosce dal CONTENUTO, non dal nome del file: i
        # fascicoli scaricati arrivano con nomi diversi da comune a comune, e
        # una determina che si chiama 'doc4.pdf' resta una determina.
        det = ' '.join(t for _, t in testi if RX_DISPOSITIVO.search(t[:2500]))
        esito = esito_da_dispositivo(det)

        # l'oggetto si prende dalla determina se c'e': e' l'unica frase che dice
        # di cosa parla la pratica. Il resto del fascicolo cita tutto — reti,
        # strade, fotovoltaico — e classificare su quello fa sembrare ogni
        # pratica una pratica di ogni tipo.
        m = re.search(r'OGGETTO:\s*(.{0,200})', det or '') or \
            re.search(r'OGGETTO:\s*(.{0,200})', intero)
        ogg = re.sub(r'\s+', ' ', m.group(1)).strip() if m else ''
        # se l'oggetto non dice di che intervento si tratta, il tipo resta
        # VUOTO. Dedurlo dal resto del fascicolo faceva risultare "pratiche
        # fotovoltaiche" delle recinzioni, perche' le misure di conservazione
        # citate in allegato nominano gli impianti di accumulo.
        tipo = classifica(ogg)
        citati = [t for t in classifica(intero) if t not in tipo]
        sito = next((f'{c} ({n})' for c, n in siti.items()
                     if c.replace(' ', '') in intero.replace(' ', '')), None)
        if re.search(r'Parco\s+(?:Regionale|Nazionale)\s+del\s+\w+', intero, re.I):
            gestore = re.search(r'Parco\s+(?:Regionale|Nazionale)\s+del\s+\w+',
                                intero, re.I).group(0)
        elif re.search(r'Regione\s+\w+\s*[-–]?\s*UO[DS]', intero, re.I):
            gestore = 'Regione (UOD/UOS)'
        else:
            gestore = None
        voci.append({
            'cup': chiave, 'oggetto': ogg[:200], 'tipo': tipo, 'citati': citati,
            'sito': sito, 'gestore': gestore,
            'procedura': ('Appropriata' if re.search(
                r'VIncA\s*[-–]\s*Appropriata|VALUTAZIONE APPROPRIATA|Livello II',
                intero, re.I) else 'Screening'),
            'esito': esito, 'particelle': particelle_citate(intero),
            'documento': os.path.relpath(testi[0][0], cartella)})

    d = {'comune': comune, 'prov': (prov or '').upper(),
         'fonte': fonte or f'lettura fascicolo {os.path.basename(cartella)}',
         'voci': voci, 'non_letti': non_letti}
    if salva:
        registra(comune, prov, voci, fonte=d['fonte'])
    return d


def main():
    import argparse
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='Precedenti VIncA gia decisi in un comune.')
    ap.add_argument('--comune', required=True)
    ap.add_argument('--prov', default=None)
    ap.add_argument('--tipo', default='fer')
    ap.add_argument('--blocco', default=None, help='blocco.json da incrociare')
    ap.add_argument('--fascicolo', default=None, help='cartella di PDF da leggere e registrare')
    A = ap.parse_args()
    if A.fascicolo:
        d = leggi_fascicolo(A.fascicolo, A.comune, A.prov)
        print(f"{len(d['voci'])} pratiche registrate · {len(d['non_letti'])} documenti non letti")
        return
    blk = {}
    if A.blocco:
        with open(A.blocco, encoding='utf-8') as f:
            blk = json.load(f)
    print(print_precedenti(contro_blocco(blk, A.comune, A.prov, tipo=A.tipo)))


if __name__ == '__main__':
    main()
