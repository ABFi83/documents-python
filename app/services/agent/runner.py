"""Loop dell'agente in un thread: avvio, ripresa dopo una risposta, annullamento.

Ogni scrittura del thread passa prima da save_run(expected=RUNNING): se il run è stato annullato o cancellato
nel frattempo la transazione viene annullata e il thread si ferma senza scrivere altro.
La conversazione è solo in append (adapter.start / step / add_tool_results): mai modificarla.
"""
import copy
import logging
from datetime import datetime

from sqlalchemy import update

from app import db
from app.models import AiConnection, RunStatus, SearchProfile, SearchRun
from app.services.agent.context import build_feedback, profile_context
from app.services.agent.prompt import SYSTEM_PROMPT, initial_message
from app.services.agent.tools import TOOLS, RunState, execute
from app.services.ai.base import AdapterError, ToolCall
from app.services.ai.registry import llm_for, search_for

ERRORE_GENERICO = 'Errore interno durante la ricerca'


def save_run(run_id: int, expected, **values) -> bool:
    """UPDATE condizionato (WHERE id AND status = expected; expected può essere una tupla di stati),
    nella transazione corrente, senza commit. False = run annullato/cancellato: rollback, non scrivere altro."""
    stati = expected if isinstance(expected, tuple) else (expected,)
    updated = db.session.execute(
        update(SearchRun).where(SearchRun.id == run_id, SearchRun.status.in_(stati)).values(**values)
    ).rowcount
    if not updated:
        db.session.rollback()
        logging.info(f'[Run {run_id}] non più {[s.name for s in stati]}: scrittura scartata')
    return bool(updated)


def _connessione(conn_id, kind):
    conn = db.session.get(AiConnection, conn_id) if conn_id else None
    if conn is None:
        raise AdapterError(f'Connessione {kind} non più disponibile')
    return conn


def _fine(run_id, status, **values):
    if save_run(run_id, RunStatus.RUNNING, status=status, end_date=datetime.utcnow(), **values):
        db.session.commit()


def run_agent(app, run_id: int) -> None:
    """Target del thread, per l'avvio (PENDING) e per la ripresa dopo una risposta (già RUNNING)."""
    with app.app_context():
        try:
            if save_run(run_id, RunStatus.PENDING, status=RunStatus.RUNNING):
                db.session.commit()
            _loop(app, run_id)
        except AdapterError as e:
            db.session.rollback()
            _fine(run_id, RunStatus.ERROR, error_message=str(e)[:200])
        except Exception:
            logging.exception(f'[Run {run_id}] errore inatteso')
            db.session.rollback()
            _fine(run_id, RunStatus.ERROR, error_message=ERRORE_GENERICO)


def _loop(app, run_id):
    run = db.session.get(SearchRun, run_id)
    if run is None or run.status != RunStatus.RUNNING:
        return
    llm = llm_for(_connessione(run.llm_connection_id, 'llm'))
    st = RunState(user_id=run.user_id, run_id=run.id, profile_id=run.profile_id,
                  search=search_for(_connessione(run.search_connection_id, 'search')),
                  counters=copy.deepcopy(run.counters), verified_urls=list(run.verified_urls))
    steps, conversation, pending = run.steps, list(run.conversation), run.pending_results
    if not conversation:
        profile = db.session.get(SearchProfile, run.profile_id) if run.profile_id else None
        conversation = llm.start(initial_message(profile.criteria if profile else {},
                                                 profile_context(run.user_id),
                                                 build_feedback(run.user_id, run.profile_id)))
    elif pending:
        # risultati in sospeso + risposta (contenuto di fai_domanda) in un unico messaggio
        conversation = llm.add_tool_results(
            conversation, [(ToolCall(**p['call']), p['content'], p['is_error']) for p in pending])
    db.session.rollback()  # chiude la lettura: niente transazione aperta durante le chiamate di rete

    while True:
        if steps >= app.config['AGENT_MAX_STEPS']:
            return _fine(run_id, RunStatus.COMPLETED, conversation=conversation, pending_results=[])
        result = llm.step(conversation, SYSTEM_PROMPT, TOOLS)
        steps += 1
        conversation = result.conversation
        if not result.tool_calls:
            return _fine(run_id, RunStatus.COMPLETED, conversation=conversation, pending_results=[], steps=steps)

        st.new_positions = []
        domanda, results = None, []
        for call in result.tool_calls:
            if call.name == 'fai_domanda':
                if domanda is None:
                    domanda = str(call.input.get('domanda') or '').strip() or '?'
                    results.append((call, None, False))  # il contenuto sarà la risposta
                else:
                    results.append((call, 'Una sola domanda alla volta: attendi la risposta alla prima', True))
                continue
            results.append((call, *execute(st, call)))

        stato = dict(counters=st.counters, verified_urls=st.verified_urls, steps=steps)
        if domanda is not None:
            pending = [{'call': {'id': c.id, 'name': c.name, 'input': c.input}, 'content': content,
                        'is_error': err} for c, content, err in results]
            if save_run(run_id, RunStatus.RUNNING, status=RunStatus.WAITING_INPUT, question=domanda,
                        conversation=conversation, pending_results=pending, **stato):
                db.session.add_all(st.new_positions)
                db.session.commit()
            return

        conversation = llm.add_tool_results(conversation, results)
        if not save_run(run_id, RunStatus.RUNNING, conversation=conversation, pending_results=[], **stato):
            return
        db.session.add_all(st.new_positions)
        db.session.commit()
