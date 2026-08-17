"""land-scout — QA ADVERSARIALE del modulo chioma (01/08/2026)

Il modulo esiste perche' il layer del vincolo forestale (art.142-g) e la
vegetazione reale sono due cose diverse, e su Morcone la differenza ha gonfiato
il blocco cinque volte. La prima versione del modulo — tessitura dell'ortofoto —
**ha fallito il proprio controllo** (Fg70/257, fascia boscata piena, misurava
7,6% e usciva "APERTA") ed e' stata sostituita da Copernicus HRL TCD 2018.

Questi test congelano quella storia, cosi' che non si ripeta:

1. i quattro valori di calibrazione, incluso quello che vale come prova
   indipendente (Fg70/136 = 12%, ottenuto anche a mano il 25/07);
2. la scelta della METRICA — media dei campioni e non quota di pixel sopra
   soglia: se qualcuno la cambia, Fg70/774 salta da ~16% a ~41% e una particella
   aperta diventa "coperta". Il valore atteso su 70/774 e' li' per quello.
3. il fatto che "non misurata" non diventi mai "zero alberi", che e' lo schema
   che questo progetto ha gia' sbagliato sei volte (SITAP, EEA, catasto);
4. che il metodo a tessitura resti marcato inaffidabile e non venga riusato.

I test di rete si dichiarano SALTATI se Copernicus non risponde: un test che
passa perche' non ha potuto verificare e' esattamente il bug che sorveglia.

Uso:  .venv/Scripts/python tests/qa_chioma.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from landscout import chioma  # noqa: E402

ESITI = []
FIXTURE = Path(__file__).resolve().parent / 'fixture_chioma_morcone.json'
TOLL = 4.0          # punti percentuali: il servizio puo' cambiare interpolazione


def check(nome, ok, atteso, ottenuto, gravita='ALTA'):
    ESITI.append((nome, ok, gravita))
    print(f"  [{'ok ' if ok else 'KO '}] {nome}")
    if not ok:
        print(f"        atteso   : {atteso}")
        print(f"        ottenuto : {ottenuto}")


def salta(nome, motivo):
    ESITI.append((nome, None, 'SALTATO'))
    print(f"  [-- ] {nome} — SALTATO: {motivo}")


# ---------------------------------------------------------------- 1. logica pura
print('\n=== 1. soglie e verdetto (offline) ===')
casi = [(0.0, 'APERTA'), (9.9, 'APERTA'), (10.0, 'ALBERATA'), (29.9, 'ALBERATA'),
        (30.0, 'COPERTA'), (100.0, 'COPERTA')]
for pct, atteso in casi:
    v = chioma.verdetto({'pct': pct}, ha=1.0)
    check(f'{pct}% -> {atteso}', v['verdetto'] == atteso, atteso, v['verdetto'],
          gravita='MEDIA')

v = chioma.verdetto({'pct': 25.0}, ha=2.0)
check('ha_utili scontati della chioma (2,0 ha al 25% -> 1,5)',
      abs(v['ha_utili'] - 1.5) < 1e-6, 1.5, v['ha_utili'])

print('\n=== 2. "non misurata" non e\' MAI "zero alberi" ===')
for arg, etichetta in ((None, 'None'), ({'pct': None, 'nota': 'servizio giu\''}, 'pct=None')):
    v = chioma.verdetto(arg, ha=3.0)
    check(f'verdetto({etichetta}) -> NON_MISURATA',
          v['verdetto'] == 'NON_MISURATA', 'NON_MISURATA', v['verdetto'])
    check(f'verdetto({etichetta}) -> ha_utili None, non 3.0',
          v['ha_utili'] is None, None, v['ha_utili'])

print('\n=== 3. applica(): coperte fuori, alberate scontate, ignote intatte ===')
A = {'ammesse': [
        {'fg': '70', 'pla': '257', 'ha': 1.13, 'netti': 1.13, 'detrazioni': {}},
        {'fg': '70', 'pla': '136', 'ha': 3.20, 'netti': 3.20, 'detrazioni': {}},
        {'fg': '99', 'pla': '1', 'ha': 2.00, 'netti': 2.00, 'detrazioni': {}}],
     'scarti': {}, 'ha_pool': 6.33, 'ha_ammessi_lordi': 6.33, 'ha_ammessi_netti': 6.33}
R = {'70_257': {'pct': 48.6, 'verdetto': 'COPERTA', 'ha_utili': 0.58},
     '70_136': {'pct': 12.3, 'verdetto': 'ALBERATA', 'ha_utili': 2.81}}
A2 = chioma.applica(A, R, escludi_coperte=True)
ids = {f"{a['fg']}_{a['pla']}": a for a in A2['ammesse']}
check('la COPERTA esce dal blocco', '70_257' not in ids, 'esclusa', sorted(ids))
check('la coperta finisce negli scarti con il motivo',
      any('chioma' in k for k in A2['scarti']), 'scarto "chioma..."', list(A2['scarti']))
check('la ALBERATA resta ma con gli ettari scontati (3,20 al 12,3% -> ~2,81)',
      abs(ids['70_136']['netti'] - 2.806) < 0.01, '~2,81 ha', ids.get('70_136', {}).get('netti'))
check('lo sconto e\' tracciato nelle detrazioni',
      ids['70_136']['detrazioni'].get('chioma_pct') == 12.3, 12.3,
      ids['70_136']['detrazioni'].get('chioma_pct'))
check('la particella SENZA misura non viene toccata...',
      ids['99_1']['netti'] == 2.00, 2.00, ids['99_1']['netti'])
check("...ma viene marcata e contata a parte",
      ids['99_1'].get('chioma') == 'non misurata' and A2['chioma']['non_misurate'] == 1,
      "chioma='non misurata', non_misurate=1",
      (ids['99_1'].get('chioma'), A2['chioma']['non_misurate']))

print('\n=== 4. il metodo a tessitura resta marcato inaffidabile ===')
src = (Path(__file__).resolve().parent.parent / 'landscout' / 'chioma.py').read_text(encoding='utf-8')
check('analizza() usa Copernicus come default, non la tessitura',
      "def analizza(ring, fonte='copernicus'" in src, "fonte='copernicus'", 'default diverso')
check('il docstring dichiara il fallimento su Fg70/257',
      '70/257' in src and 'NON VALIDATO' in src, 'menzione 70/257 + NON VALIDATO',
      'documentazione del fallimento assente')

print('\n=== 5. calibrazione congelata (rete: Copernicus HRL TCD 2018) ===')
if not FIXTURE.exists():
    salta('valori di calibrazione', f'fixture assente: {FIXTURE.name}')
else:
    fx = json.loads(FIXTURE.read_text(encoding='utf-8'))
    for k, d in sorted(fx.items()):
        try:
            r = chioma.analizza_copernicus(d['anello'])
        except chioma.TCDNonDisponibile as e:
            salta(f'{k}: TCD ~{d["atteso_pct"]}%', f'servizio non disponibile ({e})')
            continue
        att = d['atteso_pct']
        ok = abs(r['pct'] - att) <= TOLL
        extra = ('  <- prova indipendente: stesso valore ottenuto a mano il 25/07'
                 if k == '70_136' else '')
        check(f'{k}: TCD {att}% (+-{TOLL}){extra}', ok, f'{att} +-{TOLL}', r['pct'])
    # la metrica: con "quota di pixel sopra 30%" 70/774 uscirebbe intorno al 41%
    if '70_774' in fx:
        try:
            r = chioma.analizza_copernicus(fx['70_774']['anello'])
            check('la metrica e\' la MEDIA, non la quota sopra soglia '
                  '(70/774 resta ALBERATA, non COPERTA)',
                  chioma.verdetto(r)['verdetto'] == 'ALBERATA', 'ALBERATA',
                  chioma.verdetto(r)['verdetto'])
        except chioma.TCDNonDisponibile as e:
            salta('metrica = media dei campioni', str(e))

print('\n=== 6. un servizio muto alza, non restituisce zero ===')
try:
    chioma.analizza_copernicus([(41.0, 14.0), (41.0, 14.0), (41.0, 14.0)])
    check('anello degenere -> TCDNonDisponibile', False, 'eccezione', 'nessuna eccezione')
except chioma.TCDNonDisponibile:
    check('anello degenere -> TCDNonDisponibile', True, 'eccezione', 'eccezione')
except Exception as e:
    check('anello degenere -> TCDNonDisponibile', False, 'TCDNonDisponibile',
          f'{type(e).__name__}')

# ---------------------------------------------------------------- riepilogo
print('\n' + '=' * 64)
ko = [e for e in ESITI if e[1] is False]
sk = [e for e in ESITI if e[1] is None]
gravi = [e for e in ko if e[2] == 'ALTA']
print(f"  {sum(1 for e in ESITI if e[1] is True)}/{len(ESITI) - len(sk)} test superati"
      + (f" — {len(ko)} falliti ({len(gravi)} gravi)" if ko else '')
      + (f" — {len(sk)} SALTATI (rete)" if sk else ''))
for n, _, g in ko:
    print(f"   [{g}] {n}")
if sk:
    print('  [!] i test saltati NON sono test superati: la calibrazione non e\' stata verificata.')
sys.exit(1 if gravi else 0)
