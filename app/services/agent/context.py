import re
from datetime import date

from app.models import Position
from app.services.summary_service import documenti_completati, somma_estrazioni

MAX_POSITIVI, MAX_NEGATIVI, MAX_PREFERENZE = 10, 10, 15
_PESO_POS = {5: 1.0, 4: 0.6}
_PESO_NEG = {1: 1.0, 2: 0.6}
_PESO_STATO = {'candidato': 1.3, 'accettato': 1.5}
_URL_LIKE = re.compile(r'@|https?:|www\.|\w\.(com|it|org|net|io)\b', re.I)


def _scrub(testo):
    """Toglie token con '@', URL o numeri lunghi (telefoni) da un testo libero."""
    if not testo:
        return testo
    ok = [t for t in testo.split()
          if not _URL_LIKE.search(t) and sum(c.isdigit() for c in t) < 7]
    return ' '.join(ok)


def profile_context(user_id):
    """Profilo professionale dai CV COMPLETED, senza nome, cognome, description né contatti."""
    docs = documenti_completati(user_id)
    risultati = [(d.id, d.process.result or {}) for d in docs]
    somma = somma_estrazioni(risultati)
    ruoli = []
    for _, r in risultati:
        ruolo = _scrub(r.get('ruolo_obiettivo'))
        if ruolo and ruolo not in ruoli:
            ruoli.append(ruolo)
    esperienze = [{'ruolo': _scrub(e.get('ruolo')), 'azienda': _scrub(e.get('azienda')),
                   'start_date': e.get('start_date'), 'end_date': e.get('end_date')}
                  for e in somma['esperienze']]
    anni = [int(e['start_date'][:4]) for e in esperienze
            if (e['start_date'] or '')[:4].isdigit()]
    return {'ruoli_obiettivo': ruoli, 'esperienze': esperienze,
            'skill': [v['nome'] for v in somma['linguaggi'] + somma['frameworks']],
            'anni_esperienza': date.today().year - min(anni) if anni else None}


def _pesi(p):
    """(peso positivo, peso negativo) base di una posizione, prima del moltiplicatore."""
    if p.stato == 'rifiutato':
        return 0, 0
    pos = max(_PESO_POS.get(p.interesse, 0), _PESO_STATO.get(p.stato, 0))
    if pos:
        return pos, 0  # candidato/accettato (o interesse alto) non è mai negativo
    neg = _PESO_NEG.get(p.interesse, 0)
    if neg and p.stato == 'non_candidato':
        neg = 0.3
    return 0, neg


def build_feedback(user_id, profile_id):
    posizioni = Position.query.filter_by(user_id=user_id).order_by(Position.id).all()
    positivi, negativi, prefs = [], [], {}
    for p in posizioni:
        stesso = p.profile_id is not None and p.profile_id == profile_id
        molt = 1.0 if stesso else 0.5
        pos, neg = _pesi(p)
        for peso, lista in ((pos, positivi), (neg, negativi)):
            if peso:
                lista.append({'titolo': p.titolo, 'azienda': p.azienda, 'stato': p.stato,
                              'interesse': p.interesse, 'peso': round(peso * molt, 2)})
        if p.motivo_tipo == 'preferenza' and (p.motivo_preferenza or '').strip():
            testo = p.motivo_preferenza.strip()
            v = prefs.setdefault(testo.casefold(), {'testo': testo, 'n': 0, 'stesso': False})
            v['n'] += 1
            v['stesso'] = v['stesso'] or stesso
    preferenze = [{'testo': v['testo'],
                   'peso': min(2.0, (1.0 if v['stesso'] else 0.5) + 0.5 * (v['n'] - 1))}
                  for v in prefs.values()]
    ordina = lambda l, n: sorted(l, key=lambda e: -e['peso'])[:n]  # sort stabile
    # ponytail: url_gia_visti cresce senza limite; se pesa nel prompt, tenere solo gli ultimi N o passare a un tool di controllo
    visti = list(dict.fromkeys(p.url_norm for p in posizioni if p.url_norm))
    return {'positivi': ordina(positivi, MAX_POSITIVI), 'negativi': ordina(negativi, MAX_NEGATIVI),
            'preferenze_da_evitare': ordina(preferenze, MAX_PREFERENZE), 'url_gia_visti': visti}
