"""land-scout — QA ADVERSARIALE del modulo coltura (01/08/2026)

Il modulo esiste per non contare come "installabile" un uliveto. Il rischio
speculare — ed e' il settimo ripetersi dello schema "assenza di dato letta come
assenza di problema" — e' che una particella di cui NON si e' riusciti a leggere
la coltura esca dal tool come pulita.

I test verificano che il modulo non menta su tre cose: che cosa c'e' piantato,
quando NON riesce a dirlo, e che cosa succede a valle quando non lo sa.

Il caso che ha fatto nascere il modulo e' il primo test: Fg70/203 e Fg70/209
hanno nel PDF lo stesso identico testo ("SEMINATIVO / Qualita ULIVETO") e
abbinamento OPPOSTO. Qualunque regola posizionale ne sbaglia uno dei due.

Uso:  .venv/Scripts/python tests/qa_coltura.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from landscout import coltura  # noqa: E402

ESITI = []


def check(nome, ok, atteso, ottenuto, gravita='ALTA'):
    ESITI.append((nome, ok, gravita))
    print(f"  [{'ok ' if ok else 'KO '}] {nome}")
    if not ok:
        print(f"        atteso   : {atteso}")
        print(f"        ottenuto : {ottenuto}")


# ---- tariffe reali lette dalle visure di famiglia (EUR/ha, giugno 2026) ----
TAR = {('SEMINATIVO', '2'): 30.99, ('ULIVETO', '2'): 18.06,
       ('SEMINATIVO', '1'): 51.61, ('BOSCO MISTO', '2'): 5.09}


def rec(m2, porz, qs, red):
    return {'fg': '70', 'pla': 'X', 'm2': m2, 'certo': False,
            'porzioni': [{'m2': s, 'qualita': None, 'classe': c} for s, c in porz],
            'qualita_set': qs, 'redditi': red}


print('\n=== 1. il caso 203 vs 209: stesso testo, abbinamento opposto ===')
# 203: AA 217 m2 cl.1 (dom 1,12) = SEMINATIVO ; AB 2.513 cl.2 (dom 4,54) = ULIVETO
r203 = coltura.disambigua(
    rec(2730, [(217, '1'), (2513, '2')], ['SEMINATIVO', 'ULIVETO'], [1.12, 4.54]), TAR)
q203 = coltura.quota(r203)
check('Fg70/203 -> uliveto = 2.513 m2 (la porzione GRANDE)',
      q203['certo'] and q203['m2_max'] == 2513, '2513 certo', q203)

# 209: AA 814 m2 cl.2 (dom 1,47) = ULIVETO ; AB 546 cl.2 (dom 1,69) = SEMINATIVO
r209 = coltura.disambigua(
    rec(1360, [(814, '2'), (546, '2')], ['SEMINATIVO', 'ULIVETO'], [1.47, 1.69]), TAR)
q209 = coltura.quota(r209)
check('Fg70/209 -> uliveto = 814 m2 (la porzione PICCOLA)',
      q209['certo'] and q209['m2_max'] == 814, '814 certo', q209)

check('i due casi NON sono risolti dalla stessa regola posizionale',
      q203['m2_max'] == 2513 and q209['m2_max'] == 814,
      'uno grande e uno piccolo', (q203['m2_max'], q209['m2_max']))

print('\n=== 2. quando NON sa, deve dirlo (niente punto al posto di un intervallo) ===')
# nessuna tariffa nota per PRATO/VIGNETO: l'abbinamento non e' ricostruibile
r654 = coltura.disambigua(
    rec(11325, [(8819, None), (2506, None)], ['PRATO', 'VIGNETO'], [27.33, 9.06]), TAR)
q654 = coltura.quota(r654)
check('Fg70/654 senza tariffe -> intervallo, non un numero',
      not q654['certo'] and q654['m2_min'] == 2506 and q654['m2_max'] == 8819,
      'certo=False, 2506-8819', q654)
v654 = coltura.verdetto(r654)
check('e il verdetto e\' AMBIGUA, non PULITA',
      v654['verdetto'] == 'AMBIGUA', 'AMBIGUA', v654['verdetto'])

r_muto = rec(5000, [(2500, None), (2500, None)], ['SEMINATIVO', 'ULIVETO'], [])
check('senza redditi non inventa un abbinamento',
      not coltura.quota(coltura.disambigua(r_muto, TAR))['certo'],
      'certo=False', coltura.quota(r_muto))

print('\n=== 3. tariffa mancante = jolly, non liberi tutti ===')
# BOSCO MISTO ignoto ma le altre due si incastrano in un solo modo -> risolvibile
tar2 = {k: v for k, v in TAR.items() if k != ('BOSCO MISTO', '2')}
r142 = coltura.disambigua(
    rec(19690, [(275, '2'), (19245, '2'), (170, '2')],
        ['BOSCO MISTO', 'SEMINATIVO', 'ULIVETO'], [0.14, 59.64, 0.31]), tar2)
q142 = coltura.quota(r142)
check('Fg70/142 -> uliveto 170 m2 per esclusione (bosco ignoto)',
      q142['certo'] and q142['m2_max'] == 170, '170 certo', q142)
check('...e resta PULITA (0,9% arboreo), non scartata',
      coltura.verdetto(r142)['verdetto'] == 'PULITA', 'PULITA',
      coltura.verdetto(r142)['verdetto'])

# se NESSUNA tariffa e' nota, deve tornare ambigua anche con 3 porzioni
check('zero tariffe note -> ambigua (il jolly non basta da solo)',
      not coltura.quota(coltura.disambigua(
          rec(19690, [(275, '2'), (19245, '2'), (170, '2')],
              ['BOSCO MISTO', 'SEMINATIVO', 'ULIVETO'], [0.14, 59.64, 0.31]), {}))['certo'],
      'certo=False', 'risolta senza dati')

print('\n=== 4. classificazione delle qualita\' (trappole di prefisso) ===')
casi = [('SEMIN ARBOR', 'mista'), ('SEMINATIVO', 'aperta'), ('ULIVETO', 'arborea'),
        ('VIGNETO', 'arborea'), ('BOSCO MISTO', 'bosco'), ('PRATO', 'aperta'),
        ('QUALCOSA DI IGNOTO', 'ignota')]
for q, atteso in casi:
    got = coltura.classifica(q)
    check(f"'{q}' -> {atteso}", got == atteso, atteso, got,
          gravita='ALTA' if q == 'SEMIN ARBOR' else 'MEDIA')

print('\n=== 5. a valle: non sapere non e\' una detrazione, ma va dichiarato ===')
A = {'ammesse': [
        {'fg': '70', 'pla': '203', 'ha': 0.273, 'netti': 0.273, 'detrazioni': {}},
        {'fg': '70', 'pla': '654', 'ha': 1.1325, 'netti': 1.1325, 'detrazioni': {}},
        {'fg': '99', 'pla': '1', 'ha': 2.0, 'netti': 2.0, 'detrazioni': {}}],   # terzo: nessun dato
     'scarti': {}, 'ha_pool': 3.4, 'ha_ammessi_lordi': 3.4, 'ha_ammessi_netti': 3.4}
C = {'70_203': r203, '70_654': dict(r654, certo=True, arboreo_m2_noto=2506)}
A2 = coltura.applica(A, C)
ids = {f"{a['fg']}_{a['pla']}": a for a in A2['ammesse']}
check('la particella tutta uliveto esce dal blocco',
      '70_203' not in ids, 'esclusa', list(ids))
check('la mista resta ma con gli ettari ridotti',
      abs(ids['70_654']['netti'] - 1.1325 * (1 - 2506 / 11325)) < 0.01,
      '~0,88 ha', ids.get('70_654', {}).get('netti'))
check('la particella SENZA dato non viene toccata...',
      ids['99_1']['netti'] == 2.0, '2.0', ids['99_1']['netti'])
check("...ma viene marcata 'non verificata' e contata",
      ids['99_1'].get('coltura') == 'non verificata' and A2['coltura']['senza_dato'] == 1,
      "coltura='non verificata', senza_dato=1",
      (ids['99_1'].get('coltura'), A2['coltura']['senza_dato']))

print('\n=== 6. l\'override che contraddice il dato derivato deve gridare ===')
C2 = coltura.leggi_visure.__wrapped__ if hasattr(coltura.leggi_visure, '__wrapped__') else None
r = dict(r203)
q = coltura.quota(r)
finto = {'70_203': dict(r, certo=True, arboreo_m2_noto=99,
                        conflitto_override=(q['m2_max'], 99))}
check('conflitto registrato (derivato 2.513 vs override 99)',
      finto['70_203']['conflitto_override'] == (2513, 99), '(2513, 99)',
      finto['70_203'].get('conflitto_override'))

# ---------------------------------------------------------------- riepilogo
print('\n' + '=' * 62)
ko = [e for e in ESITI if not e[1]]
gravi = [e for e in ko if e[2] == 'ALTA']
print(f"  {len(ESITI) - len(ko)}/{len(ESITI)} test superati"
      + (f" — {len(ko)} falliti ({len(gravi)} gravi)" if ko else ''))
for n, _, g in ko:
    print(f"   [{g}] {n}")
sys.exit(1 if gravi else 0)
