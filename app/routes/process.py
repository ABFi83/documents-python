from flask import Blueprint, request, jsonify, send_from_directory, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from app.models import Process
from app.schemas import  ProcessSchema
from flasgger import swag_from
from werkzeug.utils import safe_join
from threading import Thread

# Configura il logging

proc_bp = Blueprint('process', __name__)
process_schema = ProcessSchema()



@proc_bp.route('/<int:process_id>', methods=['GET'])
@jwt_required()
@swag_from({
    'tags': ['Documents'],
    'parameters': [],
    'responses': {200: {'description': 'File uploaded and analyzed'}}
})
def get_process(process_id):
    user_id = get_jwt_identity()
    process = Process.query.filter_by(id=process_id, user_id=user_id).first()
    if not process:
        return jsonify({'msg': 'Process not found'}), 404
    return process_schema.jsonify(process), 202