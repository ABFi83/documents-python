from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from flasgger import swag_from
from marshmallow import ValidationError
from app import db
from app.models import SearchProfile, Position
from app.schemas import SearchProfileSchema
from app.services.summary_service import somma_estrazioni, documenti_completati

sp_bp = Blueprint('search_profiles', __name__)
schema = SearchProfileSchema()


def _own(profile_id):
    return SearchProfile.query.filter_by(id=profile_id, user_id=int(get_jwt_identity())).first()


def _unici(nomi):
    """Senza doppioni case-insensitive, vince la prima grafia."""
    visti = {}
    for n in nomi:
        if n and n.strip():
            visti.setdefault(n.strip().casefold(), n.strip())
    return list(visti.values())


def _load():
    """(dati, None) oppure (None, risposta 400)."""
    try:
        return schema.load(request.get_json(silent=True) or {}), None
    except ValidationError as e:
        return None, (jsonify({'msg': 'Dati non validi', 'errors': e.messages}), 400)


@sp_bp.route('', methods=['GET'])
@jwt_required()
@swag_from({'tags': ['SearchProfiles'], 'responses': {200: {'description': "Profili di ricerca dell'utente"}}})
def list_profiles():
    profiles = SearchProfile.query.filter_by(user_id=int(get_jwt_identity())).order_by(SearchProfile.id).all()
    return jsonify(schema.dump(profiles, many=True))


@sp_bp.route('', methods=['POST'])
@jwt_required()
@swag_from({'tags': ['SearchProfiles'],
            'parameters': [{'name': 'body', 'in': 'body', 'required': True, 'schema': {
                'type': 'object', 'required': ['name'],
                'properties': {'name': {'type': 'string'}, 'criteria': {'type': 'object'}}}}],
            'responses': {201: {'description': 'Profilo creato'}, 400: {'description': 'Dati non validi'}}})
def create_profile():
    data, err = _load()
    if err:
        return err
    profile = SearchProfile(user_id=int(get_jwt_identity()), name=data['name'], criteria=data['criteria'])
    db.session.add(profile)
    db.session.commit()
    return jsonify(schema.dump(profile)), 201


@sp_bp.route('/suggestions', methods=['GET'])
@jwt_required()
@swag_from({'tags': ['SearchProfiles'],
            'responses': {200: {'description': 'Ruoli e competenze suggeriti dai CV COMPLETED: {ruoli, competenze}'}}})
def suggestions():
    estrazioni = [(d.id, d.process.result or {}) for d in documenti_completati(int(get_jwt_identity()))]
    somma = somma_estrazioni(estrazioni)
    ruoli = [r.get('ruolo_obiettivo') for _, r in estrazioni]
    ruoli += [e.get('ruolo') for e in somma['esperienze']]  # più recenti prima
    competenze = [v['nome'] for v in somma['linguaggi'] + somma['frameworks']]
    return jsonify({'ruoli': _unici(ruoli), 'competenze': _unici(competenze)})


@sp_bp.route('/<int:profile_id>', methods=['GET'])
@jwt_required()
@swag_from({'tags': ['SearchProfiles'], 'responses': {200: {'description': 'Profilo'}, 404: {'description': 'Non trovato'}}})
def get_profile(profile_id):
    profile = _own(profile_id)
    if not profile:
        return jsonify({'msg': 'Profile not found'}), 404
    return jsonify(schema.dump(profile))


@sp_bp.route('/<int:profile_id>', methods=['PUT'])
@jwt_required()
@swag_from({'tags': ['SearchProfiles'], 'responses': {200: {'description': 'Profilo aggiornato (sostituzione completa)'},
                                                      400: {'description': 'Dati non validi'},
                                                      404: {'description': 'Non trovato'}}})
def update_profile(profile_id):
    profile = _own(profile_id)
    if not profile:
        return jsonify({'msg': 'Profile not found'}), 404
    data, err = _load()
    if err:
        return err
    profile.name, profile.criteria = data['name'], data['criteria']
    profile.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(schema.dump(profile))


@sp_bp.route('/<int:profile_id>', methods=['DELETE'])
@jwt_required()
@swag_from({'tags': ['SearchProfiles'], 'responses': {200: {'description': 'Profilo cancellato'},
                                                      404: {'description': 'Non trovato'}}})
def delete_profile(profile_id):
    profile = _own(profile_id)
    if not profile:
        return jsonify({'msg': 'Profile not found'}), 404
    Position.query.filter_by(profile_id=profile.id).update({'profile_id': None})
    db.session.delete(profile)
    db.session.commit()
    return jsonify({'msg': 'Profile deleted', 'id': profile_id})
