from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from flasgger import swag_from
from app import db
from app.models import AiConnection
from app.schemas import AiConnectionSchema
from app.services.ai import registry
from app.services.ai.base import AdapterError
from app.utils.crypto import encrypt, CryptoNotConfigured

settings_bp = Blueprint('settings', __name__)
conn_schema = AiConnectionSchema()


def _own(conn_id):
    return AiConnection.query.filter_by(id=conn_id, user_id=int(get_jwt_identity())).first()


def _encrypt_key(api_key):
    """Ritorna (token, last4) oppure solleva ValueError con messaggio sicuro."""
    try:
        return encrypt(api_key), api_key[-4:]
    except (CryptoNotConfigured, ValueError):
        raise ValueError('Cifratura non configurata (ENCRYPTION_KEY)')


def _activate(conn):
    AiConnection.query.filter(AiConnection.user_id == conn.user_id, AiConnection.kind == conn.kind,
                              AiConnection.id != conn.id).update({'active': False})
    conn.active = True


def _bad_model(provider, model):
    return model not in registry.LLM_PROVIDERS[provider]['models']


@settings_bp.route('/providers', methods=['GET'])
@jwt_required()
@swag_from({'tags': ['Settings'], 'responses': {200: {'description': 'Provider LLM (con modelli) e di ricerca disponibili'}}})
def providers():
    return jsonify(registry.providers_info())


@settings_bp.route('/connections', methods=['GET'])
@jwt_required()
@swag_from({'tags': ['Settings'], 'responses': {200: {'description': "Connessioni AI dell'utente (senza chiavi)"}}})
def list_connections():
    conns = AiConnection.query.filter_by(user_id=int(get_jwt_identity())).order_by(AiConnection.id).all()
    return jsonify(conn_schema.dump(conns, many=True))


@settings_bp.route('/connections', methods=['POST'])
@jwt_required()
@swag_from({
    'tags': ['Settings'],
    'parameters': [{'name': 'body', 'in': 'body', 'required': True, 'schema': {
        'type': 'object', 'required': ['kind', 'provider', 'api_key'],
        'properties': {'kind': {'type': 'string', 'enum': ['llm', 'search']}, 'provider': {'type': 'string'},
                       'model': {'type': 'string'}, 'api_key': {'type': 'string'}, 'active': {'type': 'boolean'}}}}],
    'responses': {201: {'description': 'Connessione creata'}, 400: {'description': 'Dati non validi'}}
})
def create_connection():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    kind, provider, api_key = data.get('kind'), data.get('provider'), data.get('api_key')
    reg = {'llm': registry.LLM_PROVIDERS, 'search': registry.SEARCH_PROVIDERS}.get(kind)
    if reg is None:
        return jsonify({'msg': 'kind deve essere llm o search'}), 400
    if provider not in reg:
        return jsonify({'msg': f'Provider non supportato: {provider}'}), 400
    if not api_key or not isinstance(api_key, str):
        return jsonify({'msg': 'api_key obbligatoria'}), 400
    model = None
    if kind == 'llm':
        model = data.get('model') or reg[provider]['default_model']
        if _bad_model(provider, model):
            return jsonify({'msg': f'Modello non supportato: {model}'}), 400
    try:
        enc, last4 = _encrypt_key(api_key)
    except ValueError as e:
        return jsonify({'msg': str(e)}), 400
    first = not AiConnection.query.filter_by(user_id=user_id, kind=kind).first()
    conn = AiConnection(user_id=user_id, kind=kind, provider=provider, model=model,
                        api_key_enc=enc, key_last4=last4, active=False)
    db.session.add(conn)
    db.session.flush()
    if first or data.get('active'):
        _activate(conn)
    db.session.commit()
    return jsonify(conn_schema.dump(conn)), 201


@settings_bp.route('/connections/<int:conn_id>', methods=['PATCH'])
@jwt_required()
@swag_from({'tags': ['Settings'], 'responses': {200: {'description': 'Connessione aggiornata'},
                                                404: {'description': 'Non trovata'}}})
def update_connection(conn_id):
    conn = _own(conn_id)
    if not conn:
        return jsonify({'msg': 'Connection not found'}), 404
    data = request.get_json(silent=True) or {}
    if data.get('model') is not None:
        if conn.kind != 'llm' or _bad_model(conn.provider, data['model']):
            return jsonify({'msg': f"Modello non supportato: {data['model']}"}), 400
        conn.model = data['model']
    if data.get('api_key'):
        try:
            conn.api_key_enc, conn.key_last4 = _encrypt_key(data['api_key'])
        except ValueError as e:
            return jsonify({'msg': str(e)}), 400
    if data.get('active') is True:
        _activate(conn)
    elif data.get('active') is False:
        conn.active = False
    db.session.commit()
    return jsonify(conn_schema.dump(conn))


@settings_bp.route('/connections/<int:conn_id>', methods=['DELETE'])
@jwt_required()
@swag_from({'tags': ['Settings'], 'responses': {200: {'description': 'Connessione cancellata'},
                                                404: {'description': 'Non trovata'}}})
def delete_connection(conn_id):
    conn = _own(conn_id)
    if not conn:
        return jsonify({'msg': 'Connection not found'}), 404
    db.session.delete(conn)
    db.session.commit()
    return jsonify({'msg': 'Connection deleted', 'id': conn_id})


@settings_bp.route('/connections/<int:conn_id>/test', methods=['POST'])
@jwt_required()
@swag_from({'tags': ['Settings'], 'responses': {200: {'description': '{"ok": true}'},
                                                400: {'description': '{"ok": false, "msg": ...}'},
                                                404: {'description': 'Non trovata'}}})
def test_connection(conn_id):
    conn = _own(conn_id)
    if not conn:
        return jsonify({'msg': 'Connection not found'}), 404
    try:
        (registry.llm_for if conn.kind == 'llm' else registry.search_for)(conn).test()
    except AdapterError as e:
        return jsonify({'ok': False, 'msg': str(e)}), 400
    return jsonify({'ok': True})
