import logging
from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import User
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

    # Cancella tutti i documenti, skill ed experience collegati all'utente
    from app.models import Document, Skill, Experience
    Document.query.filter_by(user_id=user.id).delete()
    Skill.query.filter_by(user_id=user.id).delete()
    Experience.query.filter_by(user_id=user.id).delete()
    db.session.commit()
    return jsonify(user_schema.dump(user))