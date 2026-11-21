import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from app.models import Position
from app.services.ai.base import AdapterError

TRANSITIONS = {
    'da_valutare': {'promossa', 'bocciata'},
    'promossa': {'candidato', 'non_candidato', 'bocciata', 'da_valutare'},
    'bocciata': {'da_valutare', 'promossa'},
    'non_candidato': {'candidato', 'promossa'},
    'candidato': {'accettato', 'rifiutato', 'promossa'},
    'accettato': {'candidato'},
    'rifiutato': {'candidato'},
}

_TRACKING = {'gclid', 'fbclid', 'ref', 'trk', 'trackingid'}


def normalize_url(url: str) -> str:
    try:
        p = urlsplit(url.strip())
    except ValueError:  # URL malformato (es. 'http://[bad'): si confronta la stringa grezza
        return url.strip().lower()
    query = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                   if not k.lower().startswith('utm_') and k.lower() not in _TRACKING)
    path = p.path.rstrip('/') or '/'
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, urlencode(query), ''))


def _norm(s: str) -> str:
    # i punti si tolgono (S.p.A. -> spa), altra punteggiatura -> spazio
    s = (s or '').casefold().replace('.', '')
    return ' '.join(re.sub(r'[^\w\s]|_', ' ', s).split())


def normalize_key(azienda: str, titolo: str) -> str:
    return f'{_norm(azienda)}|{_norm(titolo)}'


def find_duplicate(user_id: int, url: str, azienda: str, titolo: str):
    q = Position.query.filter_by(user_id=user_id)
    if url:
        found = q.filter_by(url_norm=normalize_url(url)).first()
        if found:
            return found
    if not (_norm(azienda) and _norm(titolo)):
        return None  # chiave incompleta: niente falsi positivi
    return q.filter_by(key_norm=normalize_key(azienda, titolo)).first()


_SCHEMA = {'type': 'object', 'properties': {
    'tipo': {'type': 'string', 'enum': ['generico', 'annuncio', 'preferenza']},
    'preferenza': {'type': ['string', 'null']}}, 'required': ['tipo']}


def _fallback(motivo: str) -> dict:
    return {'tipo': 'generico' if len(motivo.split()) < 4 else 'annuncio', 'preferenza': None}


def classify_reason(motivo: str, adapter) -> dict:
    if adapter is None:
        return _fallback(motivo)
    prompt = ("Classifica il motivo con cui un utente scarta o promuove un'offerta di lavoro.\n"
              "- generico: non spiega nulla (es. 'no', 'non mi piace').\n"
              "- annuncio: riguarda solo questa posizione o azienda.\n"
              "- preferenza: esprime una preferenza generale riutilizzabile (es. 'troppo manageriale'); "
              "in 'preferenza' scrivi la preferenza normalizzata (es. 'evitare ruoli manageriali').\n"
              f"Motivo: {motivo}")
    try:
        r = adapter.extract_json(prompt, _SCHEMA)
    except AdapterError:
        return _fallback(motivo)
    if not isinstance(r, dict) or r.get('tipo') not in ('generico', 'annuncio', 'preferenza'):
        return _fallback(motivo)
    pref = r.get('preferenza')
    pref = pref.strip() if r['tipo'] == 'preferenza' and isinstance(pref, str) and pref.strip() else None
    return {'tipo': r['tipo'], 'preferenza': pref}
