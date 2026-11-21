import json

SYSTEM_PROMPT = """Sei un agente che cerca offerte di lavoro per conto di una persona. Ricevi i criteri di ricerca, il suo profilo professionale (senza dati personali) e il riepilogo delle valutazioni passate.

Strumenti:
- cerca_web(query, max_risultati): cerca sul web; i risultati contengono titolo, URL e un estratto.
- leggi_pagina(url): legge il testo di una pagina.
- salva_posizione({...}): salva una posizione trovata.
- fai_domanda(domanda): chiede un chiarimento alla persona.

Regole:
- Usa gli strumenti: non inventare posizioni, aziende o URL.
- Salva solo posizioni la cui pagina hai davvero visto (nei risultati di cerca_web o con leggi_pagina).
- Proponi solo annunci pubblicati da non più di max_giorni_annuncio giorni (campo dei criteri).
- Non proporre URL presenti in url_gia_visti.
- Se un criterio è ambiguo o in conflitto con altri, usa fai_domanda prima di proseguire.
- Le valutazioni passate guidano la ricerca: cerca posizioni simili ai positivi, evita le caratteristiche dei negativi e le preferenze_da_evitare. Un peso maggiore di 1 indica un requisito o una preferenza forte; un peso basso, un segnale debole.
- Per ogni posizione salvata dai un punteggio da 0 a 100 e una motivazione breve.
- Quando hai finito, chiudi con un breve riepilogo di cosa hai trovato.
"""


def _sezione(titolo, dati):
    return f"## {titolo}\n{json.dumps(dati, ensure_ascii=False, indent=2, sort_keys=True)}"


def initial_message(criteria, profile, feedback):
    """Messaggio iniziale deterministico (stessi input, stesso testo: prompt caching)."""
    return "\n\n".join([
        "Cerca posizioni di lavoro adatte.",
        _sezione("Criteri di ricerca", criteria),
        _sezione("Profilo professionale", profile),
        _sezione("Valutazioni passate", feedback),
    ])
