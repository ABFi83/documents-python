"""Strumenti dell'agente: definizioni (provider-neutre) ed esecuzione con i controlli nel codice."""
import json
from dataclasses import dataclass, field

from flask import current_app

from app.models import Position
from app.services.agent.pages import PageError, read_page
from app.services.ai.base import AdapterError, SearchAdapter, ToolCall, ToolSpec
from app.services.positions import find_duplicate, normalize_key, normalize_url

_STR = {'type': 'string'}
_STR_LIST = {'type': 'array', 'items': _STR}


def _obj(props, required):
    return {'type': 'object', 'properties': props, 'required': required, 'additionalProperties': False}


TOOLS = [
    ToolSpec('cerca_web', 'Cerca sul web. Ritorna una lista di {url, titolo, snippet}.',
             _obj({'query': _STR, 'max_risultati': {'type': 'integer', 'minimum': 1, 'maximum': 10}}, ['query'])),
    ToolSpec('leggi_pagina', 'Legge il testo di una pagina web.', _obj({'url': _STR}, ['url'])),
    ToolSpec('salva_posizione',
             "Salva una posizione trovata. L'URL deve essere comparso in cerca_web o letto con leggi_pagina.",
             _obj({'url': _STR, 'titolo': _STR, 'azienda': _STR, 'luogo': _STR, 'modalita': _STR,
                   'descrizione': _STR, 'requisiti': _STR, 'data_pubblicazione': _STR, 'fonte': _STR,
                   'punteggio': {'type': 'integer', 'minimum': 0, 'maximum': 100}, 'motivazione': _STR,
                   'skill_presenti': _STR_LIST, 'skill_mancanti': _STR_LIST},
                  ['url', 'titolo', 'azienda', 'punteggio', 'motivazione', 'skill_presenti', 'skill_mancanti'])),
    ToolSpec('fai_domanda', "Fa una domanda alla persona e attende la risposta.", _obj({'domanda': _STR}, ['domanda'])),
]

_FACOLTATIVI = ('luogo', 'modalita', 'descrizione', 'requisiti', 'data_pubblicazione', 'fonte')


@dataclass
class RunState:
    """Stato del run durante un turno; il runner lo salva a fine turno."""
    user_id: int
    run_id: int
    profile_id: int | None
    search: SearchAdapter
    counters: dict
    verified_urls: list
    new_positions: list = field(default_factory=list)  # create in questo turno, non ancora nel DB

    def verifica(self, url):
        u = normalize_url(url)
        if u not in self.verified_urls:
            self.verified_urls.append(u)


def _limite(st, contatore, chiave, nome):
    if st.counters[contatore] >= current_app.config[chiave]:
        return f'limite {nome} raggiunto: concludi con quanto trovato', True
    return None


def cerca_web(st: RunState, inp: dict):
    if r := _limite(st, 'ricerche', 'AGENT_MAX_SEARCHES', 'ricerche'):
        return r
    st.counters['ricerche'] += 1
    n = inp.get('max_risultati')
    n = min(max(n, 1), 10) if isinstance(n, int) else 5
    try:
        risultati = st.search.search(str(inp.get('query') or ''), n)
    except AdapterError as e:
        return f'Ricerca non riuscita: {e}', True
    for r in risultati:
        st.verifica(r.url)
    return json.dumps([{'url': r.url, 'titolo': r.title, 'snippet': r.snippet} for r in risultati],
                      ensure_ascii=False), False


def leggi_pagina(st: RunState, inp: dict):
    if r := _limite(st, 'pagine_lette', 'AGENT_MAX_PAGES', 'pagine'):
        return r
    st.counters['pagine_lette'] += 1
    url = str(inp.get('url') or '')
    try:
        testo = read_page(url)
    except PageError as e:
        return f'Pagina non leggibile: {e}', True
    st.verifica(url)
    return testo, False


def _scarta(st, motivo, msg):
    st.counters['scartate'][motivo] += 1
    return f'{motivo}: {msg}', True


def salva_posizione(st: RunState, inp: dict):
    if r := _limite(st, 'salvate', 'AGENT_MAX_SAVED', 'posizioni salvate'):
        return r
    url, titolo, azienda = (str(inp.get(k) or '').strip() for k in ('url', 'titolo', 'azienda'))
    if not (url and titolo and azienda):
        return 'url, titolo e azienda sono obbligatori', True
    url_norm = normalize_url(url)
    if url_norm not in st.verified_urls:
        return _scarta(st, 'link_non_verificato',
                       "l'URL non è comparso in cerca_web né è stato letto con leggi_pagina in questa ricerca")
    trovata = find_duplicate(st.user_id, url, azienda, titolo)
    if trovata is not None and (trovata.interesse is not None or trovata.stato != 'da_valutare'):
        return _scarta(st, 'gia_valutata', "la persona ha già valutato questa posizione: non riproporla")
    key = normalize_key(azienda, titolo)
    key_completa = all(key.split('|'))  # come find_duplicate: niente falsi positivi su chiavi vuote
    if trovata is not None or any(p.url_norm == url_norm or (key_completa and p.key_norm == key)
                                  for p in st.new_positions):
        return _scarta(st, 'doppione', 'posizione già salvata (stesso URL o stessa azienda e titolo)')
    punteggio = inp.get('punteggio')
    st.new_positions.append(Position(
        user_id=st.user_id, run_id=st.run_id, profile_id=st.profile_id, origine='agente',
        url=url, titolo=titolo, azienda=azienda,
        punteggio_ai=punteggio if isinstance(punteggio, int) else None,
        motivazione_ai=inp.get('motivazione'),
        skill_presenti=inp.get('skill_presenti') or [], skill_mancanti=inp.get('skill_mancanti') or [],
        **{k: inp.get(k) for k in _FACOLTATIVI}))
    st.counters['salvate'] += 1
    return 'Posizione salvata', False


_ESEGUI = {'cerca_web': cerca_web, 'leggi_pagina': leggi_pagina, 'salva_posizione': salva_posizione}


def execute(st: RunState, call: ToolCall) -> tuple[str, bool]:
    """(contenuto, is_error). fai_domanda è gestito dal runner."""
    fn = _ESEGUI.get(call.name)
    if fn is None:
        return f'Strumento sconosciuto: {call.name}', True
    return fn(st, call.input or {})
