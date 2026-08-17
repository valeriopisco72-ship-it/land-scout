# -*- coding: utf-8 -*-
"""QA precedenti — i due modi in cui un registro di pratiche mente.

1. **Legge l'esito nel posto sbagliato.** Un parere di taglio bosco contiene la
   frase "divieto assoluto di esecuzione dei lavori nel periodo 1 aprile - 31
   luglio": e' una PRESCRIZIONE stagionale, non un rigetto. Cercando le parole
   su tutto il fascicolo, quattro pareri favorevoli di Morcone diventavano
   NEGATIVI alla prima stesura del modulo. L'esito si legge nel dispositivo.

2. **Deduce il tipo di intervento dagli allegati.** Le misure di conservazione
   citate in ogni fascicolo nominano gli impianti di accumulo e i parchi eolici:
   classificando sul testo intero, una recinzione anti-cinghiale risultava una
   "pratica FER". Il tipo si legge nell'oggetto; se l'oggetto non lo dice, il
   tipo resta VUOTO.

E la regola di sempre: un comune senza fascicolo letto non e' un comune senza
ostacoli. Deve dire "non lo so".
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from landscout import precedenti as PR

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


_vero = PR.REGISTRO_DIR
PR.REGISTRO_DIR = tempfile.mkdtemp()
try:
    print('\n[1] senza fascicolo letto la risposta e "non lo so"')

    R = PR.contro_blocco({'particelle': [{'fg': '70', 'pla': '136'}]}, 'Ignoto', 'BN')
    t('letto = False', R['letto'] is False, str(R['letto']), grave=True)
    t('nessun precedente inventato', R['esatti'] == [] and R['per_tipo'] == {}, grave=True)
    t('e lo dice come cosa da fare',
      any('non si sa' in a.lower() or 'NON si sa' in a for a in R['avvisi']),
      str(R['avvisi']), grave=True)
    t('i rischi riportano il vuoto', any('NON si sa' in x for x in PR.rischi(R)),
      str(PR.rischi(R)))

    print('\n[2] l esito si legge nel dispositivo, non nelle prescrizioni')

    PRESCRIZIONE = ('IL RESPONSABILE ... DETERMINA Di prendere atto ed esprimere PARERE '
                    'FAVOREVOLE in merito al progetto di taglio bosco ceduo, con le '
                    'seguenti PRESCRIZIONI: divieto assoluto di esecuzione dei lavori '
                    'nel periodo compreso tra il 1 aprile e il 31 luglio')
    t('un divieto stagionale NON e un rigetto',
      PR.esito_da_dispositivo(PRESCRIZIONE) == 'FAVOREVOLE CON PRESCRIZIONI',
      PR.esito_da_dispositivo(PRESCRIZIONE), grave=True)
    RIGETTO = ('DETERMINAZIONE DEL RESPONSABILE ... D E T E R M I N A La conclusione '
               'NEGATIVA con effetto di RIGETTO E ARCHIVIAZIONE della procedura di '
               'Screening')
    t('controprova: un rigetto vero viene letto come NEGATIVO',
      PR.esito_da_dispositivo(RIGETTO) == 'NEGATIVO', PR.esito_da_dispositivo(RIGETTO),
      grave=True)
    t('senza dispositivo l esito NON si desume dal parere',
      PR.esito_da_dispositivo('') == 'NON CONCLUSA', grave=True)
    t('e nemmeno da un sentito favorevole isolato',
      PR.esito_da_dispositivo('si esprime SENTITO FAVOREVOLE con raccomandazioni')
      in ('FAVOREVOLE', 'FAVOREVOLE CON PRESCRIZIONI'),
      'il sentito e nel dispositivo solo se il file e una determina')

    print('\n[3] il tipo si legge nell oggetto')

    t('una recinzione resta una recinzione',
      PR.classifica('REALIZZAZIONE DI RECINZIONE PER PREVENIRE I DANNI DA FAUNA')
      == ['recinzione'],
      str(PR.classifica('REALIZZAZIONE DI RECINZIONE PER PREVENIRE I DANNI DA FAUNA')),
      grave=True)
    t('controprova: "erosione eolica" non e un impianto eolico',
      'fer' not in PR.classifica('abbattimento polveri per ridurre l erosione eolica del suolo'),
      str(PR.classifica('abbattimento polveri per ridurre l erosione eolica del suolo')),
      grave=True)
    t('controprova: "impianti di accumulo" citati nelle misure non fanno una pratica FER '
      'se stanno fuori dall oggetto',
      PR.classifica('') == [], grave=True)
    t('un agrivoltaico invece si',
      'fer' in PR.classifica('impianto agrivoltaico da 20 MW'), grave=True)
    t('un taglio bosco si riconosce',
      'taglio_bosco' in PR.classifica('LAVORI DI TAGLIO BOSCHI NELLE PARTICELLE 930 E 931'),
      grave=True)

    print('\n[4] le particelle citate: senza i codici che gli stanno accanto')

    TESTO = ('Le particelle catastali interessate risultano: - Foglio 83 particelle '
             '930-931 - Foglio 69 particelle 449 - 721 - 189 - 329 213-02-02 UOS Tutela '
             'e salvaguardia ambientale')
    P = PR.particelle_citate(TESTO)
    t('prende le particelle vere', ('83', '930') in P and ('69', '449') in P, str(P),
      grave=True)
    t('controprova: il codice ufficio 213-02-02 non diventa una particella',
      ('69', '02') not in P and ('69', '213') not in P, str(P), grave=True)

    print('\n[5] senza fonte non si registra, e un esito inventato viene rifiutato')

    try:
        PR.registra('X', 'BN', [{'cup': 'C1', 'esito': 'FAVOREVOLE'}])
        alzato = False
    except ValueError:
        alzato = True
    t('registrare senza fonte alza', alzato, grave=True)
    try:
        PR.registra('X', 'BN', [{'cup': 'C1', 'esito': 'FORSE'}], fonte='f')
        alzato2 = False
    except ValueError:
        alzato2 = True
    t('un esito fuori dai quattro ammessi alza', alzato2, grave=True)

    print('\n[6] il caso Morcone: precedente esatto, stesso foglio, rigetto')

    PR.registra('Morcone', 'BN', [
        {'cup': 'C20', 'oggetto': 'taglio boschi p.lle 930-931 fg 83',
         'tipo': ['taglio_bosco'], 'esito': 'FAVOREVOLE',
         'particelle': [('83', '930'), ('83', '931')],
         'prescrizioni': ['rilascio di 1 pianta ad invecchiamento indefinito per ettaro',
                          'divieto stagionale 1 aprile - 31 luglio']},
        {'cup': 'C42', 'oggetto': 'taglio boschi fg 70', 'tipo': ['taglio_bosco'],
         'esito': 'FAVOREVOLE', 'particelle': [('70', '323'), ('70', '329')],
         'prescrizioni': ['divieto stagionale 1 aprile - 31 luglio']},
        {'cup': 'C31', 'oggetto': 'imboschimento C/da Montagna', 'tipo': ['imboschimento'],
         'esito': 'NEGATIVO', 'gestore': 'Parco Regionale del Matese',
         'motivo': 'divieto assoluto su habitat 6210/6220: modifica destinazione d uso',
         'particelle': []},
    ], fonte='fascicolo comunale', aggiornato='2026-08-12')

    BLK = {'particelle': [{'fg': '83', 'pla': '930'}, {'fg': '70', 'pla': '136'},
                          {'fg': '61', 'pla': '1'}]}
    R2 = PR.contro_blocco(BLK, 'Morcone', 'BN', tipo='imboschimento')
    t('la particella gia decisa esce come precedente ESATTO',
      [v['cup'] for v in R2['esatti']] == ['C20'], str(R2['esatti']), grave=True)
    t('il foglio in comune esce come CONTESTO, non come precedente',
      [v['cup'] for v in R2['stesso_foglio']] == ['C42'], str(R2['stesso_foglio']),
      grave=True)
    t('il foglio 61 senza precedenti non produce nulla',
      all('61' not in v.get('fogli', []) for v in R2['stesso_foglio']), grave=True)
    t('il rigetto compare nei rischi con la sua motivazione',
      any('PRECEDENTE NEGATIVO' in x and '6210' in x for x in PR.rischi(R2)),
      str(PR.rischi(R2)), grave=True)
    t('la prescrizione ricorrente (in 2 pareri) viene isolata',
      R2['prescrizioni_ricorrenti'] == ['divieto stagionale 1 aprile - 31 luglio'],
      str(R2['prescrizioni_ricorrenti']), grave=True)
    t('controprova: quella citata una volta sola NON e ricorrente',
      not any('invecchiamento' in p for p in R2['prescrizioni_ricorrenti']),
      str(R2['prescrizioni_ricorrenti']), grave=True)

    print('\n[7] un tipo mai presentato non e un tipo ammesso')

    R3 = PR.contro_blocco(BLK, 'Morcone', 'BN', tipo='fer')
    t('lo dichiara esplicitamente',
      any('nessuno ci ha ancora provato' in a for a in R3['avvisi']), str(R3['avvisi']),
      grave=True)
    t('e NON lo conta come favorevole',
      'fer' not in R3['per_tipo'], str(R3['per_tipo']), grave=True)
    t('mentre un tipo gia rigettato mette in guardia',
      any('gia RIGETTATA' in a for a in R2['avvisi']), str(R2['avvisi']), grave=True)
    t('il riepilogo si stampa', 'PRECEDENTI VIncA' in PR.print_precedenti(R2))
    t('cerca() filtra per foglio',
      [v['cup'] for v in PR.cerca('Morcone', 'BN', fg='70')] == ['C42'],
      str(PR.cerca('Morcone', 'BN', fg='70')))
    t('cerca() filtra per esito',
      [v['cup'] for v in PR.cerca('Morcone', 'BN', esito='NEGATIVO')] == ['C31'],
      grave=True)
finally:
    PR.REGISTRO_DIR = _vero

print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 72)
sys.exit(1 if FAIL else 0)
