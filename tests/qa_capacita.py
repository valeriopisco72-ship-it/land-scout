# -*- coding: utf-8 -*-
"""QA capacita' — il gate che puo' azzerare tutto il resto.

La regola qui e' piu' stretta che altrove: un errore di misura costa ettari,
un falso "rete libera" costa il progetto intero.
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from landscout import capacita as K

OK = FAIL = 0
GRAVI = []


def t(nome, cond, dett='', grave=False):
    global OK, FAIL
    if cond:
        OK += 1
        print(f'  ok   {nome}')
    else:
        FAIL += 1
        print(f'  FAIL {nome} {dett}')
        if grave:
            GRAVI.append(nome)


print('=' * 76)
print('  QA CAPACITA — criticita di rete, coda di connessione, verdetto')
print('=' * 76)

# ------------------------------------------------------------------ 1. scala
print('\n[1] scala di criticita: crescente = peggio')
t('la scala copre 0-4', set(K.SCALA) == {0, 1, 2, 3, 4})
t('4 e peggio di 1',
  'sature' in K.SCALA[4][1] and 'margine' in K.SCALA[1][1], grave=True)
t('0 NON significa "nessuna criticita" ma "dato assente"',
  'assente' in K.SCALA[0][0], grave=True)

# ------------------------------------------------------------------ 2. coda
print('\n[2] lettura della coda di connessione')
CSV = ('Regione;Provincia;Comune;Tipo Impianto;Fonte;Stato Connessione;Potenza (MW)\n'
       'CAMPANIA;BENEVENTO;MORCONE;Accumuli;Accumulo stand-alone;STMG accettate;100\n'
       'CAMPANIA;BENEVENTO;BENEVENTO;Accumuli;Accumulo stand-alone;Richieste;100\n'
       'CAMPANIA;AVELLINO;AVELLINO;Accumuli;Accumulo stand-alone;In esercizio;50\n')
p = os.path.join(tempfile.mkdtemp(), 'coda.csv')
open(p, 'w', encoding='utf-8').write(CSV)

q = K.coda_da_export(p, prov='BENEVENTO')
t('filtra per provincia', q['righe'] == 2 and q['mw_totali'] == 200.0,
  f"righe {q['righe']} mw {q['mw_totali']}", grave=True)

# Il peso e' il punto: 100 MW appena richiesti non occupano la rete come 100 MW
# autorizzati. Senza pesi la coda sovrastima la congestione.
t('la coda pesata e minore di quella lorda',
  q['mw_pesati'] < q['mw_totali'], f"pesati {q['mw_pesati']}", grave=True)
t('STMG accettate pesa piu di Richieste',
  K.PESO_STATO['stmg accettate'] > K.PESO_STATO['richieste'], grave=True)
t('atteso 100*0.6 + 100*0.15 = 75', abs(q['mw_pesati'] - 75.0) < 0.01,
  f"pesati {q['mw_pesati']}")

t('filtra anche per comune',
  K.coda_da_export(p, prov='BENEVENTO', comune='MORCONE')['mw_totali'] == 100.0)

# copertura parziale: un export di una sola tecnologia NON e' la coda del nodo
t('export monotecnologia segnalato come copertura parziale',
  q['copertura_parziale'] == 'Accumuli', f"{q['copertura_parziale']}", grave=True)
MISTO = CSV + 'CAMPANIA;BENEVENTO;X;Fotovoltaico;Solare;Richieste;10\n'
p2 = os.path.join(tempfile.mkdtemp(), 'misto.csv')
open(p2, 'w', encoding='utf-8').write(MISTO)
t('export multi-tecnologia NON segnalato come parziale (controprova)',
  K.coda_da_export(p2, prov='BENEVENTO')['copertura_parziale'] is None, grave=True)

# ------------------------------------------------------------------ 3. verdetto
print('\n[3] verdetto: mai un falso "rete libera"')
NON_VER = {'provincia': 'X', 'livello': None, 'verificato': False,
           'nota': 'servizio non raggiunto'}
v = K.valuta(NON_VER)
t('servizio non raggiunto -> NON verificata, non "libera"',
  any('NON VERIFICATA' in x for x in v['da_verificare']) and not v['punti_forti'],
  f"punti {v['punti_forti']}", grave=True)

BASSA = {'provincia': 'Milano', 'livello': 1, 'verificato': True, 'etichetta': 'bassa',
         'significato': K.SCALA[1][1], 'granularita': 'PROVINCIALE'}
ALTA = {'provincia': 'Foggia', 'livello': 4, 'verificato': True, 'etichetta': 'molto alta',
        'significato': K.SCALA[4][1], 'granularita': 'PROVINCIALE'}
t('criticita bassa = punto forte', K.valuta(BASSA)['punti_forti'], grave=True)
t('criticita massima = rischio', K.valuta(ALTA)['rischi'], grave=True)
t('anche con criticita bassa resta il limite di granularita',
  any('PROVINCIALE' in x or 'cabina' in x for x in K.valuta(BASSA)['da_verificare']),
  grave=True)

t('senza coda il fatto e dichiarato',
  any('coda' in x.lower() and 'NON verificata' in x for x in K.valuta(BASSA)['da_verificare']),
  grave=True)

# la coda va rapportata alla TAGLIA del progetto: 5.000 MW davanti a un 8 MW
# non e' lo stesso che davanti a un 500 MW
GROSSA = {'mw_totali': 5000.0, 'mw_pesati': 4000.0, 'per_stato': {}, 'per_fonte': {},
          'per_tipo': {}, 'copertura_parziale': None}
v1 = K.valuta(BASSA, GROSSA, mwp=8.9)
v2 = K.valuta(BASSA, GROSSA, mwp=2000.0)
t('coda enorme rispetto al progetto = rischio',
  any('volte la taglia' in x for x in v1['rischi']), f"{v1['rischi']}", grave=True)
t('stessa coda per un progetto grande non e lo stesso allarme (controprova)',
  not any('volte la taglia' in x for x in v2['rischi']), f"{v2['rischi']}", grave=True)

# ------------------------------------------------------------------ 4. live
print('\n[4] servizio live e-Distribuzione (se raggiungibile)')
c = K.criticita_provincia('Benevento')
if c.get('verificato') and c.get('livello') is not None:
    t('Benevento trovata nel servizio', c['provincia'].upper().startswith('BENEVENTO'))
    t('livello in scala 0-4', c['livello'] in K.SCALA, f"lv {c['livello']}")
    t('dichiara la granularita provinciale', 'PROVINCIALE' in c.get('granularita', ''),
      grave=True)
    t('dichiara che la scala e ricavata per evidenza',
      'evidenza' in c.get('scala_nota', ''), grave=True)
    # controllo di coerenza esterno: Foggia e Lecce sono notoriamente fra le
    # province piu' sature d'Italia, Milano no. Se la scala fosse invertita
    # questo confronto lo direbbe.
    fg = K.criticita_provincia('Foggia')
    mi = K.criticita_provincia('Milano')
    if fg.get('livello') is not None and mi.get('livello') is not None:
        t('Foggia risulta piu critica di Milano (controllo di verso della scala)',
          fg['livello'] > mi['livello'], f"Foggia {fg['livello']} Milano {mi['livello']}",
          grave=True)
    t('provincia inesistente -> livello None, non zero',
      K.criticita_provincia('Nonesiste')['livello'] is None, grave=True)
else:
    print('  (saltato: servizio non raggiungibile ora — e questo e proprio')
    print('   il caso in cui il tool NON deve dire "rete libera")')
    t('senza servizio il verdetto resta non verificato',
      not K.valuta(c)['punti_forti'], grave=True)

# ------------------------------------------------------------------ 5. cabine
print('\n[5] inversione di flusso: il dato per CABINA, non per provincia')
PDF = os.environ.get('LANDSCOUT_EDISTR_PDF', '')  # PDF locale, non incluso
if os.path.exists(PDF):
    inv = K.inversioni_da_pdf(PDF, prov='BN')
    t('legge le sezioni della provincia', len(inv['sezioni']) >= 8,
      f"{len(inv['sezioni'])}", grave=True)
    t('estrae i nomi delle cabine', 'PONTELANDOLFO' in inv['cabine'],
      f"{inv['cabine'][:6]}", grave=True)
    t('distingue >=5% da >=1%',
      any(r['inv_5pct'] for r in inv['sezioni']) and
      any(not r['inv_5pct'] for r in inv['sezioni']), grave=True)
    t('il filtro provincia funziona (controprova)',
      all(r['prov'] == 'BN' for r in inv['sezioni']), grave=True)
    t('altre province danno cabine diverse',
      set(K.inversioni_da_pdf(PDF, prov='AQ')['cabine']) != set(inv['cabine']))

    hit = K.cabina_critica(inv, 'PONTELANDOLFO')
    t('riconosce la cabina di riferimento', hit is not None and hit['inv_5pct'],
      f'{hit}', grave=True)
    t('una cabina non in elenco NON viene segnalata (controprova)',
      K.cabina_critica(inv, 'CABINAINESISTENTE') is None, grave=True)

    v = K.valuta(BASSA, inversioni=inv, cabina='PONTELANDOLFO')
    t('cabina satura = rischio anche se la provincia sta bene',
      any('inversione di flusso' in x for x in v['rischi']), f"{v['rischi']}", grave=True)
    v2 = K.valuta(BASSA, inversioni=inv, cabina='CABINAINESISTENTE')
    t('cabina pulita = punto forte (controprova)',
      any('NON compare' in x for x in v2['punti_forti']), grave=True)
    v3 = K.valuta(BASSA, inversioni=inv)
    t('senza cabina indicata, chiede di identificarla',
      any('identificare su quale' in x for x in v3['da_verificare']), grave=True)
else:
    print('  (saltato: PDF inversioni non disponibile)')
t('senza PDF il fatto e dichiarato non verificato',
  any('NON verificate' in x for x in K.valuta(BASSA)['da_verificare']), grave=True)

print('\n' + '=' * 76)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 76)
sys.exit(1 if GRAVI else 0)
