import logging
from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import Document, Experience, Skill, User
from app.schemas import UserSchema
from app import db
from app.utils.jwt import generate_token
from flasgger import swag_from

user_bp = Blueprint('user', __name__)
user_schema = UserSchema()

@user_bp.route('', methods=['GET'])
@jwt_required()  # Added to ensure JWT verification
@swag_from({
    'tags': ['User'],
    'responses': {200: {'description': 'User created'}}
})
def get_user():
    user_id = get_jwt_identity()
    user = User.query.filter_by(id=user_id).first()
    logging.debug(f"User ID: {user}")
    if not user:
        return jsonify({'msg': 'User not found'}), 404
    return jsonify(user_schema.dump(user))


@user_bp.route('/reset', methods=['POST'])
@jwt_required()  # Added to ensure JWT verification
@swag_from({
    'tags': ['User'],
    'responses': {200: {'description': 'User reset'}}
})
def reset():
    user_id = get_jwt_identity()
    user = User.query.filter_by(id=user_id).first()

    if not user:
        return jsonify({'msg': 'User not found'}), 404
    
    Document.query.filter_by(user_id=user.id).delete()
    Skill.query.filter_by(user_id=user.id).delete()
    Experience.query.filter_by(user_id=user.id).delete()
    db.session.commit()
    return jsonify(user_schema.dump(user))


@user_bp.route('/skill', methods=['POST'])
@jwt_required()  
@swag_from({
    'tags': ['User/Skill'],
    'requestBody': {
        'required': True,
        'content': {
            'application/json': {
                'schema': {
                    'type': 'object',
                    'properties': {
                        'skills': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'id': {'type': 'integer'},
                                    'name': {'type': 'string'}
                                },
                                'required': ['name']
                            }
                        }
                    },
                    'required': ['skills']
                }
            }
        }
    },
    'responses': {200: {'description': 'Management skills'}}
})
def skills():
    user_id = get_jwt_identity()
    user = User.query.filter_by(id=user_id).first()
    data = request.json
    if not user:
        return jsonify({'msg': 'User not found'}), 404

    # Controllo struttura body
    if not data or 'skills' not in data or not isinstance(data['skills'], list):
        return jsonify({'msg': 'Bad request: expected {"skills": [...]}' }), 400

    Skill.query.filter_by(user_id=user.id).delete()
    for skill_data in data['skills']:
        skill = Skill(name=skill_data.get('name'), level=None, user_id=user.id)
        db.session.add(skill)
    db.session.commit()
    return jsonify(user_schema.dump(user))


@user_bp.route('/skill/<int:skill_id>', methods=['DELETE'])
@jwt_required()
@swag_from({
    'tags': ['User/Skill'],
    'parameters': [
        {
            'name': 'skill_id',
            'in': 'path',
            'type': 'integer',
            'required': True,
            'description': 'ID della skill da cancellare'
        }
    ],
    'responses': {200: {'description': 'Skill eliminata'}, 404: {'description': 'Skill non trovata'}}
})
def delete_skill(skill_id):
    user_id = get_jwt_identity()
    user = User.query.filter_by(id=user_id).first()
    if not user:
        return jsonify({'msg': 'User not found'}), 404
    skill = Skill.query.filter_by(id=skill_id, user_id=user.id).first()
    if not skill:
        return jsonify({'msg': 'Skill not found'}), 404
    db.session.delete(skill)
    db.session.commit()
    return jsonify({'msg': 'Skill deleted'})


