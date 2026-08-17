# -*- coding: utf-8 -*-
"""QA enti — chi decide, e il silenzio che costa settimane.

Il modo di sbagliare qui non e' un numero storto: e' **dedurre**. "Siamo in
Campania, quindi la VINCA la fa la Regione" e' vero per la maggior parte dei
comuni e falso per Morcone, che ha la delega dal 2022. E "siamo al Sud, quindi
ZES" e' un'inferenza che nessuno puo' fare al posto del portale del SUAP.

Quindi: un comune non registrato deve dire **non verificato**, mai una risposta
per default. E un comune registrato deve portarsi dietro la fonte, perche' le
deleghe cambiano e nessuno se ne accorge.
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from landscout import enti as EN

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


# registro isolato: i test non devono sporcare quello vero
_vero = EN.REGISTRO
EN.REGISTRO = os.path.join(tempfile.mkdtemp(), 'comuni.json')
try:
    print('\n[1] un comune non registrato non ha una risposta per default')

    R = EN.competenze('Sconosciuto', 'BN', regione='Campania')
    t('registrato = False', R['registrato'] is False, str(R['registrato']), grave=True)
    vinca = [v for v in R['voci'] if v['procedura'] == 'VINCA'][0]
    t('la VINCA risulta NON verificata', vinca['verificato'] is False, str(vinca), grave=True)
    t('e non viene attribuita alla Regione per comodita',
      vinca['ente'] is None, str(vinca), grave=True)
    t('ma se la regione e in ZES unica, lo dice come cosa DA VERIFICARE',
      any('ZES' in a and 'verificare' in a for a in R['avvisi']), str(R['avvisi']),
      grave=True)
    t('e i rischi riportano il non verificato',
      any('NON verificato' in x for x in EN.rischi(R)), str(EN.rischi(R)))
    R0 = EN.competenze('Sconosciuto', 'MI', regione='Lombardia')
    t('controprova: fuori dalle regioni ZES non si nomina la ZES',
      not any('ZES' in a for a in R0['avvisi']), str(R0['avvisi']), grave=True)

    print('\n[2] senza fonte non si registra')

    try:
        EN.registra('X', 'BN', vinca_delegata=True)
        alzato = False
    except ValueError:
        alzato = True
    t('registrare senza fonte alza', alzato, grave=True)

    print('\n[3] il caso Morcone: delega VINCA + ZES unica')

    EN.registra('Morcone', 'BN', vinca_delegata=True, vinca_atto='DD 68 del 11/04/2022',
                vinca_pareri_url='http://esempio/pareri',
                suap={'numero': 7174, 'indirizzo': 'Corso Italia 129',
                      'solo_telematico': True},
                zes_unica=True, fonte='portali comunale e SUAP, 10/08/2026',
                aggiornato='2026-08-10')
    R2 = EN.competenze('Morcone', 'BN')
    v = {x['procedura']: x for x in R2['voci']}
    t('la VINCA e attribuita al COMUNE',
      v['VINCA']['ente'] == 'Comune di Morcone', str(v['VINCA']), grave=True)
    t("e cita l'atto di delega", 'DD 68' in (v['VINCA'].get('atto') or ''), grave=True)
    t('i pareri gia emessi sono riportati: sono il precedente',
      v['VINCA'].get('pareri_gia_emessi') == 'http://esempio/pareri', grave=True)
    t("l'AU va al S.U.D. ZES, non al SUAP",
      v['Autorizzazione Unica (FER)']['ente'] == 'S.U.D. ZES',
      str(v['Autorizzazione Unica (FER)']), grave=True)
    t('e i rischi lo dicono in modo azionabile',
      any('S.U.D. ZES' in x and 'non al SUAP' in x for x in EN.rischi(R2)),
      str(EN.rischi(R2)), grave=True)
    t('il SUAP dichiara che la PEC viene rifiutata',
      any('PEC' in (x.get('nota') or '') for x in R2['voci']), str(R2['voci']))
    t('la fonte viaggia col dato', 'SUAP' in (R2.get('fonte') or ''), str(R2.get('fonte')),
      grave=True)

    print('\n[4] un comune senza delega e senza ZES: risposte opposte, e verificate')

    EN.registra('Altrove', 'BN', vinca_delegata=False, zes_unica=False,
                fonte='elenco regionale comuni delegati, 10/08/2026')
    R3 = EN.competenze('Altrove', 'BN')
    v3 = {x['procedura']: x for x in R3['voci']}
    t('VINCA alla Regione', 'Regione' in v3['VINCA']['ente'], str(v3['VINCA']), grave=True)
    t('AU al SUAP comunale', 'SUAP' in v3['Autorizzazione Unica (FER)']['ente'],
      str(v3['Autorizzazione Unica (FER)']), grave=True)
    t('nessun allarme ZES', not any('ZES' in x for x in EN.rischi(R3)), str(EN.rischi(R3)),
      grave=True)
    t('e nessun rischio inventato', EN.rischi(R3) == [], str(EN.rischi(R3)), grave=True)

    print('\n[5] aggiornare un comune non lo duplica')

    EN.registra('Morcone', 'BN', vinca_delegata=True, zes_unica=True,
                fonte='riletto il 11/08/2026', aggiornato='2026-08-11')
    d = EN._carica()['comuni']
    t('una sola voce per comune',
      sum(1 for c in d if c['comune'] == 'Morcone') == 1, str(len(d)), grave=True)
    t('e vince la registrazione piu recente',
      EN.competenze('Morcone', 'BN')['aggiornato'] == '2026-08-11', grave=True)
    print()
    print('[5-bis] cio che il tool NON sa controllare va DICHIARATO, non omesso')

    # Il perimetro del Parco Nazionale del Matese non e' pubblicato da nessun
    # servizio raggiungibile. Un layer che non risponde lascia una casella vuota,
    # e una casella vuota si legge come "nessun vincolo": e' lo schema che questo
    # progetto ha gia' pagato due volte.
    EN.registra('Lacuna', 'BN', vinca_delegata=True, zes_unica=False,
                da_verificare=[{'cosa': 'perimetro del Parco Nazionale del Matese',
                                'perche': 'dentro cambia l ente e le aree idonee',
                                'fonte': 'DM MASE 101 del 22/04/2025 all. A'}],
                fonte='verifica endpoint del 12/08/2026')
    R6 = EN.competenze('Lacuna', 'BN')
    t('la lacuna esce fra le voci da verificare',
      len(R6['da_verificare']) == 1, str(R6.get('da_verificare')), grave=True)
    t('e finisce nei rischi con la fonte per andarsela a prendere',
      any('DA VERIFICARE A MANO' in x and 'DM MASE 101' in x for x in EN.rischi(R6)),
      str(EN.rischi(R6)), grave=True)
    t('il riepilogo la stampa col perche',
      'dentro cambia l ente' in EN.print_competenze(R6),
      EN.print_competenze(R6)[-200:], grave=True)
    t('controprova: un comune senza lacune non ne inventa',
      EN.competenze('Altrove', 'BN').get('da_verificare') == []
      and not any('DA VERIFICARE' in x for x in EN.rischi(EN.competenze('Altrove', 'BN'))),
      str(EN.rischi(EN.competenze('Altrove', 'BN'))), grave=True)

    print()
    print('[5-quater] il CDU: un limite censito ma mai stampato non esiste')

    # `cdu.py` censiva dal 14/07/2026 quali comuni hanno un WebGIS e quali no,
    # per "rendere il limite esplicito nei report invece di tacerlo". Nessuno lo
    # chiamava: il limite non compariva da nessuna parte. Stesso difetto di
    # `ispezione`, trovato con lo stesso audit del 12/08/2026.
    EN.registra('Morcone', 'BN', vinca_delegata=True, zes_unica=True,
                cod_catastale='F717', fonte='audit 12/08/2026', aggiornato='2026-08-12')
    Rc = EN.competenze('Morcone', 'BN')
    voci_cdu = [v for v in Rc['voci'] if v['procedura'].startswith('CDU')]
    t('la voce CDU compare fra le competenze', len(voci_cdu) == 1, str(Rc['voci']),
      grave=True)
    t('e per Morcone dice che il WebGIS esiste ma la verifica e MANUALE',
      'manuale' in (voci_cdu[0]['nota'] or ''), str(voci_cdu), grave=True)
    EN.registra('SenzaWebgis', 'BN', vinca_delegata=True, zes_unica=False,
                cod_catastale='B541', fonte='audit 12/08/2026')
    v2 = [v for v in EN.competenze('SenzaWebgis', 'BN')['voci']
          if v['procedura'].startswith('CDU')]
    t('per un comune senza WebGIS rimanda all ufficio tecnico',
      'ufficio tecnico' in (v2[0]['nota'] or '').lower(), str(v2), grave=True)
    EN.registra('MaiCensito', 'BN', vinca_delegata=True, zes_unica=False,
                cod_catastale='Z999', fonte='audit 12/08/2026')
    v3 = [v for v in EN.competenze('MaiCensito', 'BN')['voci']
          if v['procedura'].startswith('CDU')]
    t('un comune non censito esce come NON verificato, non come pulito',
      v3 and v3[0]['verificato'] is False, str(v3), grave=True)
    t('controprova: senza codice catastale non si inventa una voce CDU',
      not any(v['procedura'].startswith('CDU')
              for v in EN.competenze('Altrove', 'BN')['voci']), grave=True)

    t('il riepilogo si stampa', 'ENTI COMPETENTI' in EN.print_competenze(R2))

    print('\n[6] il "sentito" dipende dal SITO, non dal comune')

    # A Morcone due particelle nello stesso comune hanno due enti diversi: la
    # Regione per la ZPS del Tammaro, il Comitato del Parco Nazionale del Matese
    # per la ZSC del Monte Mutria. Scrivere a quello sbagliato non e' un errore
    # di forma: e' l'ente che ha rigettato l'unica pratica rigettata.
    EN.registra('Duegestori', 'BN', vinca_delegata=True, zes_unica=False,
                gestori=[{'sito': 'ZPS IT8020015', 'ente': 'Regione Campania UOS 213.02.02'},
                         {'sito': 'ZSC IT8020009',
                          'ente': 'Comitato Parco Nazionale del Matese',
                          'nota': 'DM MASE 101/2025'}],
                fonte='fascicolo comunale letto il 12/08/2026')
    R4 = EN.competenze('Duegestori', 'BN')
    gest = [v for v in R4['voci'] if v['procedura'].startswith('sentito')]
    t('escono ENTRAMBI i gestori', len(gest) == 2, str(gest), grave=True)
    t('ciascuno col suo sito',
      {v['procedura'].split('— ')[-1] for v in gest} == {'ZPS IT8020015', 'ZSC IT8020009'},
      str([v['procedura'] for v in gest]), grave=True)
    t('e un avviso dice di verificare QUALE sito tocca la particella',
      any('PIU di un soggetto gestore' in a for a in R4['avvisi']), str(R4['avvisi']),
      grave=True)
    R5 = EN.competenze('Altrove', 'BN')
    t('controprova: un comune con un solo gestore non genera quell avviso',
      not any('PIU di un soggetto gestore' in a for a in R5['avvisi']), str(R5['avvisi']),
      grave=True)
    t('controprova: e un comune senza gestori registrati non ne inventa',
      not any(v['procedura'].startswith('sentito') for v in R5['voci']), str(R5['voci']),
      grave=True)
finally:
    EN.REGISTRO = _vero

print('\n' + '=' * 72)
print(f'  RISULTATO: {OK}/{OK+FAIL} pass   ·   {FAIL} FAIL ({len(GRAVI)} gravi)')
if GRAVI:
    print('  GRAVI: ' + ', '.join(GRAVI))
print('=' * 72)
sys.exit(1 if FAIL else 0)
