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
    if not user:
        return jsonify({'msg': 'User not found'}), 404
    return user_schema.jsonify(user)
