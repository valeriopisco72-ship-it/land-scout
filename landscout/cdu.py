"""land-scout cdu — stato della destinazione urbanistica (CDU) per comune.

L'Italia non ha una fonte unica per il CDU: dove esiste un WebGIS comunale il dato si consulta
(per ora manualmente), altrove serve richiesta all'ufficio tecnico. Questo modulo rende il
limite ESPLICITO nei report invece di tacerlo.

Stato censimento (14/07/2026). Fornitore rilevato per il Sannio: GeneGIS/pagis.it (*.servizigis.it);
il viewer è dietro ClientArea.aspx (sessione ASP.NET) -> API da reverse in una fase dedicata.
"""

REGISTRY = {
    'F717': {  # Morcone (BN)
        'comune': 'Morcone', 'stato': 'webgis-manuale',
        'url': 'https://morcone.servizigis.it/Home.aspx?page=14&webgislinkid=LINK_WEB_GIS_PUC',
        'note': 'PUC per particella via "Ricerca per Attributi" -> livello Particelle (manuale). '
                'Viewer GeneGIS/pagis dietro ClientArea.aspx: automazione possibile ma da reverse. '
                'CDU gia\' verificati a mano 07/2026 per i fogli famiglia (tutti "E agricola integrale").',
    },
    'B541': {'comune': 'Campolattaro', 'stato': 'assente',
             'note': 'Nessun WebGIS (verificato 07/2026). CDU solo da ufficio tecnico comunale.'},
    'G848': {'comune': 'Pontelandolfo', 'stato': 'assente',
             'note': 'pontelandolfo.servizigis.it non esiste (DNS). CDU da ufficio tecnico.'},
    'C719': {'comune': 'Circello', 'stato': 'incerto',
             'note': 'circello.servizigis.it risponde 503 (13/07/2026): ricontrollare periodicamente.'},
}

def cdu_status(codice_comune):
    """Ritorna lo stato CDU per il codice catastale comune (es. 'F717')."""
    e = REGISTRY.get(codice_comune)
    if e is None:
        return {'comune': codice_comune, 'stato': 'sconosciuto',
                'nota_report': 'CDU: fonte non censita — verificare se esiste WebGIS comunale, '
                               'altrimenti richiesta all\'ufficio tecnico.'}
    frasi = {
        'webgis-manuale': f"CDU: consultabile sul WebGIS comunale ({e.get('url', '')}) — verifica manuale.",
        'assente': 'CDU: nessun WebGIS comunale — necessaria richiesta all\'ufficio tecnico.',
        'incerto': 'CDU: WebGIS comunale al momento non raggiungibile — riprovare o ufficio tecnico.',
    }
    return {**e, 'nota_report': frasi[e['stato']]}


if __name__ == '__main__':
    import sys
    for c in (sys.argv[1:] or REGISTRY):
        s = cdu_status(c)
        print(f"{c} {s['comune']:>14s} | {s['stato']:15s} | {s['nota_report']}")
