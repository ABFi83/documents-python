from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from flasgger import swag_from
from app import db
from app.models import Position, PositionEvent
from app.schemas import PositionSchema, PositionEventSchema
from app.services.ai.base import AdapterError
from app.services.ai.registry import active_connection, llm_for
from urllib.parse import urlsplit

from app.services.agent.pages import read_page, PageError
from app.services.positions import TRANSITIONS, classify_reason, extract_position, find_duplicate

pos_bp = Blueprint('positions', __name__)
schema = PositionSchema()
event_schema = PositionEventSchema()


def _own(pid):
    return Position.query.filter_by(id=pid, user_id=int(get_jwt_identity())).first()


def _not_found():
    return jsonify({'msg': 'Position not found'}), 404


def _adapter(user_id):
    """Adattatore LLM attivo; None se assente o inutilizzabile (si usa la regola minima)."""
    conn = active_connection(user_id, 'llm')
    if not conn:
        return None
    try:
        return llm_for(conn)
    except AdapterError:
        return None


@pos_bp.route('', methods=['GET'])
@jwt_required()
@swag_from({'tags': ['Positions'], 'parameters': [
    {'name': n, 'in': 'query', 'type': 'string'} for n in ('stato', 'profile_id', 'run_id', 'origine')],
    'responses': {200: {'description': 'Posizioni, più recenti prima'}}})
def list_positions():
    q = Position.query.filter_by(user_id=int(get_jwt_identity()))
    for campo in ('stato', 'origine'):
        if request.args.get(campo):
            q = q.filter(getattr(Position, campo) == request.args[campo])
    for campo in ('profile_id', 'run_id'):
        if request.args.get(campo):
            try:
                q = q.filter(getattr(Position, campo) == int(request.args[campo]))
            except ValueError:
                return jsonify({'msg': f'{campo} non valido'}), 400
    return jsonify(schema.dump(q.order_by(Position.created_at.desc(), Position.id.desc()).all(), many=True))


@pos_bp.route('/manual', methods=['POST'])
@jwt_required()
@swag_from({'tags': ['Positions'],
            'parameters': [{'name': 'body', 'in': 'body', 'required': True, 'schema': {
                'type': 'object', 'properties': {
                    'url': {'type': 'string'}, 'testo': {'type': 'string'},
                    'stato_iniziale': {'type': 'string', 'default': 'candidato'},
                    'interesse': {'type': 'integer'}}}}],
            'responses': {201: {'description': 'Posizione creata'},
                          200: {'description': 'Doppione: posizione esistente, duplicato true'},
                          400: {'description': 'Dati non validi o nessuna connessione LLM'},
                          409: {'description': 'Prima il voto'},
                          422: {'description': 'pagina_non_leggibile / estrazione_fallita'},
                          502: {'description': 'ai_non_disponibile'}}})
def manual_position():
    user_id = int(get_jwt_identity())
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'msg': 'Body JSON non valido'}), 400
    url, testo = body.get('url'), body.get('testo')
    for v in (url, testo):
        if v is not None and not isinstance(v, str):
            return jsonify({'msg': 'url e testo devono essere stringhe'}), 400
    url, testo = (url or '').strip(), (testo or '').strip()
    if not url and not testo:
        return jsonify({'msg': 'Serve url o testo'}), 400
    stato = body.get('stato_iniziale', 'candidato')
    if stato not in TRANSITIONS:
        return jsonify({'msg': 'stato_iniziale non valido'}), 400
    n = body.get('interesse')
    if n is not None and (type(n) is not int or not 1 <= n <= 5):
        return jsonify({'msg': 'interesse deve essere un intero tra 1 e 5'}), 400
    if stato != 'da_valutare' and n is None:
        return jsonify({'msg': 'Prima il voto: assegna un interesse da 1 a 5'}), 409
    adapter = _adapter(user_id)
    if adapter is None:
        return jsonify({'msg': 'Nessuna connessione LLM attiva'}), 400
    if not testo:
        try:
            testo = read_page(url)
        except PageError:
            return jsonify({'code': 'pagina_non_leggibile', 'msg': "Incolla il testo dell'annuncio"}), 422
    try:
        d = extract_position(adapter, testo, url)
    except AdapterError as e:
        return jsonify({'code': 'ai_non_disponibile', 'msg': str(e)}), 502
    except ValueError:
        return jsonify({'code': 'estrazione_fallita',
                        'msg': "Non riesco a ricavare titolo e azienda: incolla il testo dell'annuncio"}), 422
    dup = find_duplicate(user_id, url, d['azienda'], d['titolo'])
    if dup:
        return jsonify({**schema.dump(dup), 'duplicato': True})
    if url and not d['fonte']:
        d['fonte'] = (urlsplit(url).hostname or '')[:200] or None
    p = Position(user_id=user_id, url=url or None, origine='manuale', stato=stato, interesse=n, **d)
    db.session.add(p)
    db.session.flush()
    db.session.add(PositionEvent(position_id=p.id, da_stato=None, a_stato=stato, interesse=n,
                                 nota='inserimento manuale'))
    db.session.commit()
    return jsonify(schema.dump(p)), 201


@pos_bp.route('/<int:pid>', methods=['GET'])
@jwt_required()
@swag_from({'tags': ['Positions'], 'responses': {200: {'description': 'Posizione con eventi'},
                                                 404: {'description': 'Non trovata'}}})
def get_position(pid):
    p = _own(pid)
    if not p:
        return _not_found()
    eventi = PositionEvent.query.filter_by(position_id=pid).order_by(PositionEvent.created_at, PositionEvent.id).all()
    return jsonify({**schema.dump(p), 'eventi': event_schema.dump(eventi, many=True)})


@pos_bp.route('/<int:pid>/vote', methods=['POST'])
@jwt_required()
@swag_from({'tags': ['Positions'],
            'parameters': [{'name': 'body', 'in': 'body', 'required': True, 'schema': {
                'type': 'object', 'required': ['interesse'], 'properties': {'interesse': {'type': 'integer'}}}}],
            'responses': {200: {'description': 'Posizione votata'}, 400: {'description': 'Voto non valido'},
                          404: {'description': 'Non trovata'}}})
def vote(pid):
    p = _own(pid)
    if not p:
        return _not_found()
    n = (request.get_json(silent=True) or {}).get('interesse')
    if type(n) is not int or not 1 <= n <= 5:
        return jsonify({'msg': 'interesse deve essere un intero tra 1 e 5'}), 400
    p.interesse = n
    db.session.add(PositionEvent(position_id=p.id, da_stato=p.stato, a_stato=p.stato, interesse=n))
    db.session.commit()
    return jsonify(schema.dump(p))


@pos_bp.route('/<int:pid>/status', methods=['POST'])
@jwt_required()
@swag_from({'tags': ['Positions'],
            'parameters': [{'name': 'body', 'in': 'body', 'required': True, 'schema': {
                'type': 'object', 'required': ['stato'], 'properties': {
                    'stato': {'type': 'string'}, 'nota': {'type': 'string'}, 'motivo': {'type': 'string'},
                    'conferma_generico': {'type': 'boolean'}}}}],
            'responses': {200: {'description': 'Posizione aggiornata'},
                          400: {'description': 'Transizione o dati non validi'},
                          404: {'description': 'Non trovata'}, 409: {'description': 'Prima il voto'},
                          422: {'description': 'motivo_generico: riscrivere o confermare'}}})
def change_status(pid):
    p = _own(pid)
    if not p:
        return _not_found()
    body = request.get_json(silent=True) or {}
    nuovo = body.get('stato')
    motivo = body.get('motivo')
    if motivo is not None and not isinstance(motivo, str):
        return jsonify({'msg': 'motivo non valido'}), 400
    motivo = (motivo or '').strip()
    if p.interesse is None:
        return jsonify({'msg': 'Prima il voto: assegna un interesse da 1 a 5'}), 409
    if nuovo not in TRANSITIONS.get(p.stato, ()):
        return jsonify({'msg': f'Transizione non consentita: {p.stato} -> {nuovo}'}), 400
    if nuovo == 'bocciata' and not motivo:
        return jsonify({'msg': 'Motivo obbligatorio per la bocciatura'}), 400
    if motivo:
        c = classify_reason(motivo, _adapter(p.user_id))
        if c['tipo'] == 'generico' and body.get('conferma_generico') is not True:
            return jsonify({'code': 'motivo_generico',
                            'msg': 'Motivo troppo generico: riscrivilo o conferma'}), 422
        p.motivo, p.motivo_tipo, p.motivo_preferenza = motivo, c['tipo'], c['preferenza']
    db.session.add(PositionEvent(position_id=p.id, da_stato=p.stato, a_stato=nuovo,
                                 interesse=p.interesse, nota=body.get('nota')))
    p.stato = nuovo
    db.session.commit()
    return jsonify(schema.dump(p))


@pos_bp.route('/<int:pid>', methods=['DELETE'])
@jwt_required()
@swag_from({'tags': ['Positions'], 'responses': {200: {'description': 'Posizione cancellata'},
                                                 404: {'description': 'Non trovata'}}})
def delete_position(pid):
    p = _own(pid)
    if not p:
        return _not_found()
    PositionEvent.query.filter_by(position_id=pid).delete()
    db.session.delete(p)
    db.session.commit()
    return jsonify({'msg': 'Position deleted', 'id': pid})
