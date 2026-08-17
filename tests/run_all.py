# -*- coding: utf-8 -*-
"""Lancia tutta la suite e restituisce UN esito.

Perche' esiste (audit 08/08/2026): i file di QA erano quattordici script
autonomi, con tre formati di riepilogo diversi e — soprattutto — sei di loro
uscivano con codice 0 quando i fallimenti non erano classificati "gravi". Una
regressione media passava inosservata in qualunque esecuzione automatica.

Qui l'esito e' uno solo e la regola e' netta: **un test fallito e' un fallimento**,
grave o no. La distinzione grave/non grave resta utile dentro i singoli file per
capire dove guardare per primo, non per decidere se il verde e' verde.

Uso:  .venv/Scripts/python tests/run_all.py [-q]
"""
import io
import os
import re
import subprocess
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)

# i tre formati storici di riepilogo, in un solo posto
RE_SOMMARIO = re.compile(r'(\d+)\s*/\s*(\d+)\s*(?:pass\b|PASS\b|test superati)')


def esito(nome, uscita, codice):
    m = RE_SOMMARIO.findall(uscita)
    passati, totali = (int(m[-1][0]), int(m[-1][1])) if m else (0, 0)
    ok = codice == 0 and totali > 0 and passati == totali
    return {'file': nome, 'pass': passati, 'tot': totali, 'exit': codice, 'ok': ok,
            'muto': totali == 0}


def main():
    quieto = '-q' in sys.argv
    files = sorted(f for f in os.listdir(QUI)
                   if f.startswith('qa_') and f.endswith('.py'))
    ris = []
    t0 = time.time()
    for f in files:
        p = subprocess.run([sys.executable, os.path.join(QUI, f)],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', cwd=RADICE,
                           env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        r = esito(f, (p.stdout or '') + (p.stderr or ''), p.returncode)
        ris.append(r)
        stato = 'ok  ' if r['ok'] else 'FAIL'
        print(f"  {stato} {f:<24s} {r['pass']:>4d}/{r['tot']:<4d} (exit {r['exit']})")
        if not r['ok'] and not quieto:
            for riga in ((p.stdout or '') + (p.stderr or '')).splitlines():
                if 'FAIL' in riga or 'Traceback' in riga or riga.strip().startswith('['):
                    print('        ' + riga.strip()[:140])

    tot = sum(r['tot'] for r in ris)
    ps = sum(r['pass'] for r in ris)
    rotti = [r['file'] for r in ris if not r['ok']]
    muti = [r['file'] for r in ris if r['muto']]
    print('\n' + '=' * 74)
    print(f'  {ps}/{tot} test superati in {len(ris)} file '
          f'({time.time() - t0:.0f}s)')
    if muti:
        # un file che non stampa un riepilogo non e' un file senza fallimenti:
        # e' un file di cui non sappiamo niente
        print(f'  SENZA RIEPILOGO (non contati): {", ".join(muti)}')
    if rotti:
        print(f'  FALLITI: {", ".join(rotti)}')
    print('=' * 74)
    return 1 if rotti else 0


if __name__ == '__main__':
    sys.exit(main())
