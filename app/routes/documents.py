from flask import Blueprint, logging, request, jsonify, send_from_directory, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from app.models import Document
from app.schemas import DocumentSchema
from flasgger import swag_from
import os
import uuid
import logging
from werkzeug.utils import safe_join

# Configura il logging

doc_bp = Blueprint('documents', __name__)
document_schema = DocumentSchema()
documents_schema = DocumentSchema(many=True)

@doc_bp.route('', methods=['POST'])
@jwt_required()
@swag_from({
    'tags': ['Documents'],
    'parameters': [],
    'responses': {200: {'description': 'File uploaded'}}
})
def upload():
    user_id = get_jwt_identity()
    title = request.form['title']
    metadata = request.form['metadata']
    file = request.files['file']

    existing = Document.query.filter_by(user_id=user_id, title=title).order_by(Document.version.desc()).first()
    version = existing.version + 1 if existing else 1

    filename = f"{uuid.uuid4()}_{file.filename}"
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    os.makedirs(current_app.config['UPLOAD_FOLDER'], exist_ok=True)
    file.save(path)

    doc = Document(user_id=user_id, title=title, metadata=metadata, file_path=path, version=version)
    db.session.add(doc)
    db.session.commit()
    return document_schema.jsonify(doc)

@doc_bp.route('', methods=['GET'])
@jwt_required()
def get_documents():
    logging.debug("Inizio funzione get_documents")
    user_id = get_jwt_identity()
    logging.debug(f"User ID: {user_id}")
    query = Document.query.filter_by(user_id=user_id)
    
    if 'title' in request.args:
        logging.debug(f"Filtro per titolo: {request.args['title']}")
        query = query.filter(Document.title.ilike(f"%{request.args['title']}%"))

    if 'metadata' in request.args:
        logging.debug(f"Filtro per metadata: {request.args['metadata']}")
        query = query.filter(Document.metadata.ilike(f"%{request.args['metadata']}%"))

    documents = query.all()
    logging.debug(f"Documenti trovati: {documents}")

    return documents_schema.jsonify(documents)

@doc_bp.route('/download/<int:doc_id>', methods=['GET'])
@jwt_required()
def download(doc_id):
    logging.debug(f"Inizio download documento con ID: {doc_id}")
    doc = Document.query.get_or_404(doc_id)
    logging.debug(f"Documento trovato: {doc.user_id}, {doc.title}, {doc.file_path}")
    
    if doc.user_id != int(get_jwt_identity()):
        return jsonify({'msg': 'Unauthorized'}), 403

    # Usa safe_join per costruire il percorso sicuro
    file_name = os.path.basename(doc.file_path)
    file_path = safe_join(current_app.config['UPLOAD_FOLDER'], file_name)
    logging.debug(f"Percorso sicuro del file: {file_path}")

    # Verifica se il file esiste
    if not os.path.exists(file_path):
        logging.error(f"File non trovato: {file_path}")
        return jsonify({'msg': 'File not found'}), 404

    # Passa solo il nome del file a send_from_directory
    return send_from_directory(
        directory=current_app.config['UPLOAD_FOLDER'],
        filename=file_name,  # Usa 'filename' invece di 'path'
        as_attachment=True
    )