import logging
from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import User
from app.schemas import UserSchema
from app import db
from app.utils.jwt import generate_token
from flasgger import swag_from

auth_bp = Blueprint('auth', __name__)
user_schema = UserSchema()

@auth_bp.route('/register', methods=['POST'])
@swag_from({
    'tags': ['Auth'],
    'parameters': [{'name': 'body', 'in': 'body', 'schema': {'username': 'str', 'password': 'str'}}],
    'responses': {200: {'description': 'User created'}}
})
def register():
    data = request.json
    hashed_pw = generate_password_hash(data['password'])
    user = User(username=data['username'], password=hashed_pw, name=data['name'], surname=data['surname'])
    db.session.add(user)
    db.session.commit()
    return user_schema.jsonify(user)

@auth_bp.route('/login', methods=['POST'])
@swag_from({
    'tags': ['Auth'],
    'parameters': [{'name': 'body', 'in': 'body', 'schema': {'username': 'str', 'password': 'str'}}],
    'responses': {200: {'description': 'Token returned'}}
})
def login():
    logging.debug("User login attempt")
    data = request.json
    user = User.query.filter_by(username=data['username']).first()
    if user and check_password_hash(user.password, data['password']):
        token = generate_token(user.id)
        return jsonify(access_token=token)
    return jsonify({'msg': 'Bad credentials'}), 401
