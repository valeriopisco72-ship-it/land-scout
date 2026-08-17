"""land-scout — VAM (v0.1, 16/07/2026): Valori Agricoli Medi per provincia e coltura.

## Che cosa sono (e cosa NON sono)

I VAM sono fissati ogni anno dalla **Commissione Provinciale Espropri** di ciascuna
provincia, per **regione agraria** e **tipo di coltura**, in €/ettaro (art. 41 DPR 327/2001).

⚠️ **NON sono valori di mercato.** Sono valori amministrativi per il calcolo dell'indennita'
di esproprio, e sono sistematicamente PIU' BASSI del mercato. La **Corte Costituzionale
(sent. 181/2011)** ha dichiarato incostituzionale il VAM come criterio unico proprio perche'
scollegato dal valore venale reale. Usarli come "quanto vale il mio terreno" ripeterebbe
esattamente l'errore che questo modulo esiste per correggere.

**A cosa servono davvero qui**: sono un riferimento **ufficiale, per provincia e coltura,
aggiornato annualmente** → ottimi come **pavimento** e come indicatore **relativo** fra
province. Sostituiscono la banda nazionale 10-25k €/ha che era priva di significato.

## Perche' il caricamento e' semi-manuale

La fonte canonica e' l'Agenzia delle Entrate (un PDF per provincia per anno, dalla pagina
regionale OMI). ⚠ **Aggiornamento 18/07**: l'AdE e' **raggiungibile dalla macchina locale**
(IP italiano) — il "403 Akamai su tutto" annotato il 16/07 era dell'ambiente cloud di allora,
NON un blocco reale. Con uno User-Agent da browser la pagina Campania risponde 200 e i link
ai PDF (`.../<SIGLA>_<ANNO>.pdf`) sono scaricabili. Resta comunque **semi-manuale** perche'
il layout della tabella **cambia per ogni Commissione** e va gestito caso per caso:
  - RM 2024 -> header "Regione Agraria N° 1", coltura "Sem. Irriguo"        -> si parsa
  - VT 2023 -> header "REGIONE AGRARIA N°1",  coltura "Seminativo irriguo"   -> si parsa
  - BN/AV/CE/NA 2018-19 (Campania) -> "REGIONE AGRARIA N°: 1" affiancate 2/pagina, l'ultima
      R.A. da sola sull'ultima pagina -> ha richiesto 2 fix (regex intestazione + riga con
      piu' R.A. invece di >=2)                                              -> si parsa
  - RI 2023 -> **PDF SCANSIONATO**: 0 tabelle, 0 testo                      -> serve OCR

Quindi: il parser gestisce le varianti che sa gestire e **si rifiuta rumorosamente** quando
non ce la fa. Un PDF scansionato NON deve diventare "nessun vincolo di prezzo" o "0 €/ha":
e' la stessa trappola del NaN-box e del 'CLEAN? (SITAP non raggiunto)'.

Schema d'uso: scaricare il PDF dalla pagina regionale OMI e darlo a `--carica`. E' lo stesso
schema gia' usato per la Carta Habitat regionale e per nodi.json.

CLI:
  .venv/Scripts/python -m landscout.vam --carica data/raw/vam/VAM-RM-2024.pdf --prov RM --anno 2024
  .venv/Scripts/python -m landscout.vam --prov RM                 (consulta)
  .venv/Scripts/python -m landscout.vam --stato                   (copertura)
"""
import argparse, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass

from landscout.config import DATA, norm_prov, PROV_REGIONE

REGISTRO = DATA / 'raw' / 'vam' / 'vam.json'

# Le colture che ci interessano per il rinnovabile: terra pianeggiante e lavorabile.
# Ogni Commissione le nomina a modo suo -> qui le forme ESATTE viste sul campo.
#
# ⚠ Solo match ESATTI, niente prefissi larghi. Due bug trovati in QA 16/07:
#  1. 'Sem. Irriguo' catturato da 'sem.' -> finiva in `seminativo` (l'irriguo vale ~40% in
#     piu': inquinava il range dell'asciutto);
#  2. peggio: 'Seminativo', 'Sem. Arborato' e 'Sem. Arb. Irr.' cadevano tutte nello stesso
#     secchio e, siccome si scriveva `colture[slug][ra] = v`, **l'ultima riga sovrascriveva
#     le precedenti in silenzio**. Per la R.A. 1 di Roma il seminativo vero e' 12.300 ma
#     usciva 20.400 (valore di 'Sem. Arb. Irr.'), e il massimo 41.000 veniva in realta' da
#     'Sem. Arborato'. Nessun crash: solo numeri sbagliati con l'aria di essere ufficiali.
# 'arborato' = con alberi, 'irriguo' = irrigato: sono colture DIVERSE dal seminativo nudo,
# e per un impianto a terra e' il seminativo nudo il riferimento giusto. Restano fuori.
COLTURE_TARGET = {
    'seminativo':        ('seminativo', 'sem.', 'seminativo asciutto', 'seminativo nudo',
                          'seminativo semplice'),
    'seminativo_irriguo':('seminativo irriguo', 'sem. irriguo', 'sem.irriguo',
                          'seminativo irrig.', 'seminativo irriguo'),
    'prato':             ('prato', 'prato asciutto', 'prato stabile'),
    'pascolo':           ('pascolo',),      # 'cespugliato'/'arborato' = colture diverse: fuori
    'incolto':           ('incolto', 'incolto produttivo', 'incolto sterile'),
}


# variante -> slug, ordinate dalla PIU' SPECIFICA alla piu' generica.
# ⚠ Bug trovato in QA 16/07: con un match "prima che combacia", 'Sem. Irriguo' veniva
# catturato da 'sem.' e finiva in `seminativo` invece che in `seminativo_irriguo`.
# Effetto: i valori dell'irriguo (che vale ~40% in piu') inquinavano il secchio
# dell'asciutto -> il range VAM di Roma usciva 11.900–52.000 €/ha, ma quel 52.000 era
# un valore IRRIGUO. Corruzione silenziosa del dato, non un crash. Fix: la variante piu'
# lunga vince sempre, e i confronti sono su parola intera.
_VARIANTI = sorted(
    ((v, slug) for slug, vs in COLTURE_TARGET.items() for v in vs),
    key=lambda x: -len(x[0]))


def _slug_coltura(nome):
    """Solo match ESATTI (a meno della punteggiatura/spazi). Una coltura che non
    riconosciamo torna None e viene semplicemente ignorata: meglio un dato in meno che un
    dato sbagliato in un secchio che non gli appartiene."""
    n = re.sub(r'\s+', ' ', (nome or '').strip().lower()).strip(' .:')
    if not n:
        return None
    for v, slug in _VARIANTI:                      # specifica -> generica
        if n == v or n == v.rstrip('.'):
            return slug
    return None


def _num(cella):
    """'12.300' / '1.234,50' / '' -> float | None. Mai 0 di default: assente e' assente."""
    if not cella:
        return None
    s = re.sub(r'[^\d.,]', '', str(cella)).strip()
    if not s:
        return None
    s = s.replace('.', '').replace(',', '.')          # formato italiano
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None                        # 0 €/ha non e' un valore, e' un buco


def _e_intestazione_ra(cella):
    """Riconosce 'Regione Agraria N° 1' / 'REGIONE AGRARIA N°1' / 'REGIONE AGRARIA N°: 1'
    (Benevento/Campania, con i due punti) / 'R.A. 1' -> 1.

    ⚠ Bug 18/07: la vecchia regex `...N?\\s*°?\\s*([\\d\\s]+)` pretendeva che dopo il '°'
    ci fossero solo spazi e cifre. Benevento scrive 'N°: 1' (due punti) e il '°' viene
    decodificato come '\\ufffd' -> fra 'N' e il numero c'era spazzatura non prevista, la
    regex falliva e l'INTERA tabella veniva scartata come 'layout non gestito'. Ora si
    ancora su 'AGRARIA'/'R.A.' e si prende il primo gruppo di cifre, qualunque cosa ci sia
    in mezzo (':', '°', '\\ufffd', spazi)."""
    t = re.sub(r'\s+', ' ', str(cella or '')).upper()
    m = re.search(r'(?:REGIONE\s*AGRARIA|R\.?\s?A\.?)\D*?(\d[\d\s]*)', t)
    if not m:
        return None
    n = re.sub(r'\s', '', m.group(1))                  # 'N ° 1 0' -> '10'
    return int(n) if n.isdigit() else None


def _norm_comune(s):
    """Normalizza un nome comune per il confronto: maiuscole, spazi singoli, senza
    accenti/punteggiatura. 'Morcone' / 'MORCONE ,' -> 'MORCONE'. Serve perche' il match
    comune->regione agraria non deve fallire per un apostrofo o un accento."""
    import unicodedata
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', s.upper()).strip(' .,;:-')


def _comuni_per_ra(page):
    """Estrae {ra: {'nome': str, 'comuni': [..]}} dall'intestazione della pagina.

    I VAM elencano, sotto ogni 'REGIONE AGRARIA N° X', il nome della R.A. e i suoi comuni
    ('Comuni di: A, B, C'). Nel layout affiancato (Campania) due R.A. stanno una a sinistra
    e una a destra: si separano per posizione x della parola, non si possono leggere a righe
    intere (i comuni delle due colonne si mescolano sulla stessa riga). Su una pagina con una
    sola R.A. si usa la larghezza intera."""
    W, H = page.width, page.height
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False) or []
    if not words:
        return {}
    y_tab = min((w['top'] for w in words if w['text'].upper().startswith('COLTUR')),
                default=H * 0.45)
    head = [w for w in words if w['top'] < y_tab]

    def testo(lo, hi):
        ws = sorted([w for w in head if lo <= w['x0'] < hi], key=lambda w: (round(w['top']), w['x0']))
        righe, cur, last = [], [], None
        for w in ws:
            if last is None or abs(w['top'] - last) <= 3:
                cur.append(w['text'])
            else:
                righe.append(' '.join(cur)); cur = [w['text']]
            last = w['top']
        if cur:
            righe.append(' '.join(cur))
        return '\n'.join(righe)

    def ra_nome_comuni(txt):
        righe = txt.splitlines()
        ra = ra_idx = None
        for i, r in enumerate(righe):
            n = _e_intestazione_ra(r)
            if n:
                ra, ra_idx = n, i
                break
        if ra is None:
            return None
        nome = []
        for r in righe[ra_idx + 1:]:
            if re.match(r'\s*comuni\s+di', r, re.I):
                break
            nome.append(r)
        m = re.search(r'comuni\s+di\s*:?(.*)', txt, re.I | re.S)
        comuni = []
        if m:
            for c in re.sub(r'\s+', ' ', m.group(1)).split(','):
                c = _norm_comune(c)
                if c:
                    comuni.append(c)
        return ra, re.sub(r'\s+', ' ', ' '.join(nome)).strip(' .,'), comuni

    out = {}
    left = ra_nome_comuni(testo(0, W / 2))
    right = ra_nome_comuni(testo(W / 2, W))
    coppie = [x for x in (left, right) if x] or [ra_nome_comuni(testo(0, W))]
    for x in coppie:
        if not x:
            continue
        ra, nome, comuni = x
        d = out.setdefault(ra, {'nome': nome, 'comuni': []})
        if nome and not d['nome']:
            d['nome'] = nome
        d['comuni'].extend(comuni)
    return out


def parse_pdf(path):
    """PDF -> {'colture': {slug: {ra: eur_ha}}, 'ra': [n], 'comuni_ra': {ra:{nome,comuni}}, ...}.
    Alza ValueError se il PDF non e' interpretabile: MAI ritornare un dizionario vuoto
    che il chiamante possa scambiare per 'nessun valore'."""
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError('serve pdfplumber: .venv/Scripts/pip install pdfplumber')

    colture, ra_viste, avvisi = {}, set(), []
    comuni_ra = {}
    with pdfplumber.open(path) as pdf:
        n_pag = len(pdf.pages)
        testo_tot = ''
        for pag in pdf.pages:
            testo_tot += (pag.extract_text() or '')
            try:
                for ra, info in _comuni_per_ra(pag).items():
                    d = comuni_ra.setdefault(ra, {'nome': info.get('nome', ''), 'comuni': []})
                    if info.get('nome') and not d['nome']:
                        d['nome'] = info['nome']
                    for c in info.get('comuni', []):
                        if c not in d['comuni']:
                            d['comuni'].append(c)
            except Exception:
                pass   # l'estrazione comuni e' un di piu': non deve far fallire il parse dei valori
            for tab in pag.extract_tables() or []:
                # trova la riga di intestazione con le regioni agrarie.
                # ⚠ Bug 18/07: prima si pretendeva `>= 2` R.A. per riga (layout affiancato a
                # due colonne). Ma una provincia con numero DISPARI di regioni agrarie ha
                # un'ultima pagina con UNA SOLA R.A. (Benevento: RA1-2, RA3-4, poi RA5 da sola)
                # -> quella pagina veniva scartata in silenzio e i suoi valori sparivano dal
                # range, che pero' continuava a dichiararsi completo. Stessa famiglia del
                # troncamento SITAP/ArcGIS. Ora si prende la riga con PIU' intestazioni (>=1).
                col2ra = {}
                for riga in tab:
                    trovate = {i: n for i, c in enumerate(riga) if (n := _e_intestazione_ra(c))}
                    if len(trovate) > len(col2ra):
                        col2ra = trovate
                if not col2ra:
                    continue
                ra_viste |= set(col2ra.values())
                for riga in tab:
                    etichetta = riga[0] if riga else None
                    slug = _slug_coltura(etichetta)
                    if not slug:
                        continue
                    for i, ra in col2ra.items():
                        if i >= len(riga):
                            continue
                        v = _num(riga[i])
                        if not v:
                            continue
                        cella = colture.setdefault(slug, {})
                        pre = cella.get(str(ra))
                        # MAI sovrascrivere in silenzio: se due righe diverse pretendono la
                        # stessa casella (slug, regione agraria) e' un'ambiguita' del PDF, non
                        # un aggiornamento. Si tiene il primo e si dichiara il conflitto.
                        if pre is not None and abs(pre - v) > 0.01:
                            avvisi.append(
                                f'conflitto {slug} R.A.{ra}: gia\' {pre:,.0f} da una riga '
                                f'precedente, "{str(etichetta).strip()}" dice {v:,.0f} '
                                f'-> tengo {pre:,.0f}'.replace(',', '.'))
                            continue
                        cella[str(ra)] = v

    if not colture:
        if len(testo_tot.strip()) < 40:
            raise ValueError(
                f'PDF non interpretabile ({Path(path).name}, {n_pag} pag): nessun testo estraibile '
                '= quasi certamente una SCANSIONE. Serve OCR, oppure la versione digitale del '
                'documento. NON viene registrato nulla: un PDF illeggibile non e\' "nessun dato".')
        raise ValueError(
            f'PDF leggibile ma nessuna tabella VAM riconosciuta ({Path(path).name}): '
            'il layout di questa Commissione non e\' fra quelli gestiti. Estratto: '
            + re.sub(r'\s+', ' ', testo_tot[:160]))
    return {'colture': colture, 'ra': sorted(ra_viste), 'avvisi': avvisi, 'pagine': n_pag,
            'comuni_ra': comuni_ra}


# ---------------------------------------------------------------- registro
def _carica_registro():
    if REGISTRO.exists():
        return json.loads(REGISTRO.read_text(encoding='utf-8'))
    return {}


def _salva_registro(d):
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRO.with_suffix('.tmp')
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(REGISTRO)


def registra(path, prov, anno, fonte=None):
    prov = norm_prov(prov)
    if prov not in PROV_REGIONE:
        raise ValueError(f'provincia "{prov}" non riconosciuta')
    d = parse_pdf(path)
    reg = _carica_registro()
    reg[prov] = {'prov': prov, 'regione': PROV_REGIONE[prov], 'anno': int(anno),
                 'colture': d['colture'], 'regioni_agrarie': d['ra'],
                 'avvisi_parsing': d['avvisi'],
                 'fonte': fonte or Path(path).name,
                 'nota': 'VAM = valore amministrativo di esproprio, sotto il valore di mercato '
                         '(Corte Cost. 181/2011): usare come pavimento, non come prezzo'}
    _salva_registro(reg)
    return reg[prov]


def vam(prov, coltura='seminativo'):
    """Ritorna {'eur_ha': (min,max), 'anno', 'n_ra', 'fonte'} o None se la provincia non c'e'.

    None significa "non lo so", e il chiamante DEVE dirlo. Non esiste un fallback nazionale:
    era proprio quello il bug (banda 10-25k uguale per tutta Italia)."""
    v = _carica_registro().get(norm_prov(prov))
    if not v:
        return None
    c = (v.get('colture') or {}).get(coltura)
    if not c:
        return None
    vals = [x for x in c.values() if x]
    if not vals:
        return None
    return {'eur_ha': (min(vals), max(vals)), 'anno': v['anno'], 'coltura': coltura,
            'n_ra': len(vals), 'prov': v['prov'], 'fonte': v['fonte'], 'nota': v['nota']}


def stato():
    reg = _carica_registro()
    return {'province_caricate': sorted(reg), 'n': len(reg), 'totale_province': len(PROV_REGIONE),
            'copertura_pct': round(100 * len(reg) / len(PROV_REGIONE), 1),
            'registro': str(REGISTRO)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--carica', help='PDF VAM da importare')
    ap.add_argument('--prov'); ap.add_argument('--anno'); ap.add_argument('--fonte')
    ap.add_argument('--coltura', default='seminativo')
    ap.add_argument('--stato', action='store_true')
    A = ap.parse_args()
    if A.stato:
        s = stato()
        print(f"VAM caricati: {s['n']}/{s['totale_province']} province ({s['copertura_pct']}%)")
        print('  ' + (', '.join(s['province_caricate']) or '(nessuna)'))
        print(f"  registro: {s['registro']}")
        return
    if A.carica:
        if not (A.prov and A.anno):
            sys.exit('servono --prov e --anno')
        try:
            v = registra(A.carica, A.prov, A.anno, A.fonte)
        except (ValueError, RuntimeError) as e:
            sys.exit(f'✗ {e}')
        print(f"✓ {v['prov']} {v['anno']}: {len(v['colture'])} colture, "
              f"{len(v['regioni_agrarie'])} regioni agrarie")
        for slug, c in v['colture'].items():
            vals = list(c.values())
            print(f"   {slug:20} {min(vals):>9,.0f} – {max(vals):>9,.0f} €/ha  ({len(vals)} R.A.)".replace(',', '.'))
        for a in v.get('avvisi_parsing') or []:
            print(f'   ⚠ {a}')
        return
    if A.prov:
        v = vam(A.prov, A.coltura)
        if not v:
            print(f'✗ nessun VAM per {norm_prov(A.prov)} / {A.coltura}: '
                  'provincia non caricata (usa --carica) — e NON esiste un ripiego nazionale')
            return
        print(f"{v['prov']} {v['anno']} · {v['coltura']}: "
              f"{v['eur_ha'][0]:,.0f} – {v['eur_ha'][1]:,.0f} €/ha su {v['n_ra']} regioni agrarie".replace(',', '.'))
        print(f"  fonte: {v['fonte']}\n  ⚠ {v['nota']}")
        return
    ap.print_help()


if __name__ == '__main__':
    main()
