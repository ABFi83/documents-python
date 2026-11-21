from datetime import datetime
from threading import Thread

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flasgger import swag_from

from app import db
from app.models import ACTIVE_RUN, Position, RunStatus, SearchRun
from app.schemas import PositionSchema, SearchRunSchema
from app.services.agent.runner import run_agent, save_run

runs_bp = Blueprint('runs', __name__)
run_schema = SearchRunSchema()
pos_schema = PositionSchema(many=True)


def _own(run_id):
    return SearchRun.query.filter_by(id=run_id, user_id=int(get_jwt_identity())).first()


def _not_found():
    return jsonify({'msg': 'Run not found'}), 404


@runs_bp.route('/<int:run_id>', methods=['GET'])
@jwt_required()
@swag_from({'tags': ['Runs'], 'responses': {
    200: {'description': 'Run (status, question, counters, steps, ...) con le posizioni salvate in "positions"'},
    404: {'description': 'Non trovato'}}})
def get_run(run_id):
    run = _own(run_id)
    if not run:
        return _not_found()
    positions = Position.query.filter_by(run_id=run.id).order_by(Position.id).all()
    return jsonify({**run_schema.dump(run), 'positions': pos_schema.dump(positions)})


@runs_bp.route('/<int:run_id>/answer', methods=['POST'])
@jwt_required()
@swag_from({'tags': ['Runs'],
            'parameters': [{'name': 'body', 'in': 'body', 'required': True, 'schema': {
                'type': 'object', 'required': ['testo'], 'properties': {'testo': {'type': 'string'}}}}],
            'responses': {202: {'description': 'Risposta inviata, il run riparte'}, 400: {'description': 'testo mancante'},
                          404: {'description': 'Non trovato'}, 409: {'description': 'Il run non è in WAITING_INPUT'}}})
def answer(run_id):
    run = _own(run_id)
    if not run:
        return _not_found()
    testo = (request.get_json(silent=True) or {}).get('testo')
    if not isinstance(testo, str) or not testo.strip():
        return jsonify({'msg': 'testo obbligatorio'}), 400
    # la risposta diventa il contenuto del risultato di fai_domanda (l'unico con content null)
    pending = [{**p, 'content': testo} if p['call']['name'] == 'fai_domanda' and p['content'] is None else p
               for p in run.pending_results or []]
    if run.status != RunStatus.WAITING_INPUT or not save_run(
            run.id, RunStatus.WAITING_INPUT, status=RunStatus.RUNNING, question=None, pending_results=pending):
        return jsonify({'msg': 'Il run non è in attesa di una risposta'}), 409
    db.session.commit()
    Thread(target=run_agent, args=(current_app._get_current_object(), run.id)).start()
    return jsonify(run_schema.dump(run)), 202


@runs_bp.route('/<int:run_id>/cancel', methods=['POST'])
@jwt_required()
@swag_from({'tags': ['Runs'], 'responses': {200: {'description': 'Run annullato'}, 404: {'description': 'Non trovato'},
                                            409: {'description': 'Run già concluso'}}})
def cancel(run_id):
    run = _own(run_id)
    if not run:
        return _not_found()
    if not save_run(run.id, ACTIVE_RUN, status=RunStatus.CANCELLED, end_date=datetime.utcnow()):
        return jsonify({'msg': 'Run già concluso'}), 409
    db.session.commit()
    return jsonify(run_schema.dump(run))


@runs_bp.route('/<int:run_id>', methods=['DELETE'])
@jwt_required()
@swag_from({'tags': ['Runs'], 'responses': {200: {'description': 'Run cancellato (le posizioni restano, run_id null)'},
                                            404: {'description': 'Non trovato'}}})
def delete_run(run_id):
    run = _own(run_id)
    if not run:
        return _not_found()
    # un thread ancora attivo non troverà più il run (save_run -> False) e non scriverà nulla
    Position.query.filter_by(run_id=run.id).update({'run_id': None})
    db.session.delete(run)
    db.session.commit()
    return jsonify({'msg': 'Run deleted', 'id': run_id})
