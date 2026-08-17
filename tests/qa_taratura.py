# -*- coding: utf-8 -*-
"""QA taratura — il modo in cui una statistica vera diventa un'affermazione falsa.

Il registro di esempio riproduce la forma di un caso reale: 36 pratiche favorevoli su 37 concluse, il
97%. La frase che nasce da quel numero — «qui passa tutto, passera' anche il
nostro impianto» — e' falsa, perche' nessuna di quelle 44 pratiche riguarda un
impianto: sono recinzioni, tagli boschivi, case.

Il modulo deve rendere impossibile quel passaggio. Non nascondendo il numero,
ma vincolandone l'uso: `tasso_positivo` esiste sempre, `tasso_spendibile` esiste
solo quando la base e' pertinente alla tecnologia.

Il secondo test che conta: con un solo rigetto su 37, dichiarare il modello
"validato sui precedenti" e' un abuso, perche' un modello che risponda sempre
"favorevole" otterrebbe il 97% senza sapere nulla.
"""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from landscout import precedenti as PR
from landscout import taratura as TA

OK = FAIL = 0
GRAVI = []


def t(nome, cond, dettaglio='', grave=False):
    global OK, FAIL
    if cond:
        OK += 1
        print(f'  ok   {nome}')
    else:
        FAIL += 1
        print(f'  FAIL {nome} {dettaglio}')
        if grave:
            GRAVI.append(nome)


def _registro(tmp, comune, prov, voci):
    """Scrive un registro sintetico e lo rende l'unico visibile."""
    p = os.path.join(tmp, f'{comune.lower()}_{prov.lower()}.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump({'comune': comune, 'prov': prov, 'fonte': 'test',
                   'aggiornato': None, 'voci': voci}, f)


def _v(cup, tipo, esito, particelle=None, motivo=None, sito='IT-TEST'):
    return {'cup': cup, 'proponente': None, 'oggetto': f'oggetto {cup}',
            'tipo': tipo if isinstance(tipo, list) else [tipo], 'citati': [],
            'sito': sito, 'gestore': 'Ente Test', 'procedura': 'Screening',
            'esito': esito, 'motivo': motivo, 'particelle': particelle or [],
            'ha': None, 'data': None, 'giorni_istruttoria': None,
            'prescrizioni': [], 'documento': None}


# ─── 1. dati veri di Morcone ────────────────────────────────────────────────
print('\n--- registro di esempio ---')
B = TA.base_osservata('Esempio', 'XX')
t('il registro di esempio si legge', B is not None, grave=True)
if B:
    t('44 pratiche registrate', B['pratiche'] == 44, str(B['pratiche']), grave=True)
    t('37 concluse (36 positive + 1 negativa)',
      B['concluse'] == 37 and B['positive'] == 36 and B['negative'] == 1,
      f"concluse={B['concluse']} pos={B['positive']} neg={B['negative']}", grave=True)
    t('7 non concluse escluse dai tassi', B['non_concluse'] == 7, str(B['non_concluse']))
    t('ZERO pratiche su impianti energetici', B['fer'] == 0, str(B['fer']), grave=True)
    t('il tipo piu frequente e la recinzione',
      max(B['per_tipo'].items(), key=lambda kv: kv[1])[0] == 'recinzione',
      str(B['per_tipo']))
    t('il negativo e censito con il suo motivo',
      len(B['negativi_dettaglio']) == 1 and 'DIVIETO ASSOLUTO' in B['negativi_dettaglio'][0]['motivo'],
      str(B['negativi_dettaglio'])[:120], grave=True)
    t('e il negativo NON e georiferito',
      B['negativi_dettaglio'][0]['georiferito'] is False, grave=True)

T = TA.taratura('Esempio', 'XX', tech='BESS')
t('il tasso positivo viene calcolato (97%)',
  T['tasso_positivo'] is not None and 0.96 <= T['tasso_positivo'] <= 0.98,
  str(T['tasso_positivo']))
t('ma NON e spendibile per il BESS', T['tasso_spendibile'] is None,
  str(T['tasso_spendibile']), grave=True)
t('e la ragione nomina i tipi realmente presenti',
  'recinzione' in T['trasferibilita']['ragione'], T['trasferibilita']['ragione'][:120])
t('il potere discriminante e dichiarato insufficiente',
  T['potere_discriminante']['utilizzabile'] is False, grave=True)
t('con la baseline del modello banale esplicitata',
  0.96 <= T['potere_discriminante']['baseline_banale'] <= 0.98,
  str(T['potere_discriminante']['baseline_banale']))

A = TA.argomenti_trattativa(T)
t('produce argomenti difendibili', len(A['difendibili']) >= 3, str(len(A['difendibili'])))
t('ogni argomento difendibile porta un etichetta di provenienza',
  all(a.startswith('[osservato]') for a in A['difendibili']), grave=True)
t('e avverte di NON usare il 97% per il BESS',
  any('NON dire' in a and '%' in a for a in A['da_non_dire']),
  str(A['da_non_dire'])[:150], grave=True)
t('e di NON dichiarare il modello validato',
  any('validato' in a for a in A['da_non_dire']), grave=True)
t('e di NON collocare il diniego altrove',
  any('collocabile' in a for a in A['da_non_dire']), grave=True)

R = TA.print_taratura(T)
t('il report si stampa', 'TARATURA SUI PRECEDENTI' in R)
t('il report mostra il NO alla spendibilita', 'spendibile' in R and ' NO' in R)

# ─── 2. casi sintetici ──────────────────────────────────────────────────────
print('\n--- casi sintetici ---')
_vero = PR.REGISTRO_DIR
try:
    tmp = tempfile.mkdtemp()
    PR.REGISTRO_DIR = tmp

    # comune mai istruito: deve dire "non lo so", non zero
    T0 = TA.taratura('Ignoto', 'XX')
    t('un comune senza fascicolo non produce uno zero',
      T0['disponibile'] is False and 'non equivale' in T0['ragione'].lower(),
      str(T0)[:120], grave=True)
    A0 = TA.argomenti_trattativa(T0)
    t('e non produce argomenti', A0['difendibili'] == [] and A0['nota'])

    # registro a maggioranza FER: il tasso diventa spendibile
    voci = [_v(f'F{i}', 'fer', 'FAVOREVOLE') for i in range(8)]
    voci += [_v(f'R{i}', 'recinzione', 'FAVOREVOLE') for i in range(2)]
    _registro(tmp, 'Ferrolandia', 'BN', voci)
    T1 = TA.taratura('Ferrolandia', 'BN', tech='agriPV')
    t('con 80% di pratiche FER il tasso diventa spendibile',
      T1['tasso_spendibile'] is not None and T1['trasferibilita']['trasferibile'],
      str(T1['trasferibilita']), grave=True)
    t('ma resta descritto come indicazione, non previsione',
      'non come previsione' in T1['trasferibilita']['ragione'])

    # una sola FER su dieci: sotto la soglia, non si trasferisce
    voci = [_v('F0', 'fer', 'FAVOREVOLE')] + [_v(f'R{i}', 'recinzione', 'FAVOREVOLE')
                                              for i in range(9)]
    _registro(tmp, 'Sottosoglia', 'BN', voci)
    T2 = TA.taratura('Sottosoglia', 'BN')
    t('una sola pratica FER su dieci non basta',
      T2['tasso_spendibile'] is None and T2['trasferibilita']['quota_pertinente'] == 0.1,
      str(T2['trasferibilita']), grave=True)

    # abbastanza rigetti: il potere discriminante si sblocca
    voci = [_v(f'F{i}', 'fer', 'FAVOREVOLE') for i in range(10)]
    voci += [_v(f'N{i}', 'fer', 'NEGATIVO', particelle=[['70', '136']],
                motivo='habitat') for i in range(6)]
    _registro(tmp, 'Contrastata', 'BN', voci)
    T3 = TA.taratura('Contrastata', 'BN')
    t('con 6 rigetti il registro diventa utilizzabile',
      T3['potere_discriminante']['utilizzabile'] is True,
      str(T3['potere_discriminante']), grave=True)
    t('e conta quanti rigetti sono georiferiti',
      T3['potere_discriminante']['negativi_georiferiti'] == 6,
      str(T3['potere_discriminante']['negativi_georiferiti']))
    A3 = TA.argomenti_trattativa(T3)
    t('e allora non avverte piu sul "validato"',
      not any('validato' in a for a in A3['da_non_dire']), str(A3['da_non_dire'])[:120])

    # pratiche tutte ferme: nessun tasso
    _registro(tmp, 'Ferma', 'BN', [_v(f'X{i}', 'fer', 'NON CONCLUSA') for i in range(5)])
    T4 = TA.taratura('Ferma', 'BN')
    t('nessuna pratica conclusa: nessun tasso inventato',
      T4['tasso_positivo'] is None and T4['tasso_spendibile'] is None,
      str(T4['tasso_positivo']), grave=True)
    t('e il potere discriminante lo dice',
      T4['potere_discriminante']['utilizzabile'] is False)

    # e_fer() legge il tipo, non l'oggetto
    t('e_fer riconosce i tipi di impianto',
      TA.e_fer(_v('A', 'fotovoltaico', 'FAVOREVOLE')) and
      TA.e_fer(_v('B', ['agricolo', 'bess'], 'FAVOREVOLE')))
    t('e non scambia una recinzione per un impianto',
      not TA.e_fer(_v('C', 'recinzione', 'FAVOREVOLE')), grave=True)
    t('tipo assente non e un impianto', not TA.e_fer(_v('D', [], 'FAVOREVOLE')))
finally:
    PR.REGISTRO_DIR = _vero

print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 72)
sys.exit(1 if FAIL else 0)
