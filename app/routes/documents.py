from flask import Blueprint, request, jsonify, send_from_directory, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from app.models import Document, Process, ProcessStatus
from app.schemas import DocumentHistorySchema, ProcessSchema
from flasgger import swag_from
import os
import uuid
import logging
from werkzeug.utils import safe_join, secure_filename
from threading import Thread
from app.services.extract_service import extract_info_from_text, save_process
from app.services.text_service import pdf_to_text
from app.services.summary_service import somma_estrazioni, documenti_completati

doc_bp = Blueprint('documents', __name__)
history_schema = DocumentHistorySchema()
processes_schema = ProcessSchema(many=True)

def analyze_file(app, process_id, original_name, data):
    """Thread: testo del PDF (Docling, fallback PyPDF2) -> estrazione salvata in process.result.
    Se il CV viene cancellato durante l'analisi non scrive nulla (vedi save_process)."""
    with app.app_context():
        if db.session.get(Process, process_id) is None:
            return  # cancellato prima che il thread partisse: niente Docling
        db.session.rollback()  # chiude la lettura: non tenere aperta la transazione durante Docling
        try:
            text = pdf_to_text(app.config['DOCLING_URL'], original_name, data)
        except Exception as e:
            logging.error(f"Error analyzing file: {str(e)}")
            if save_process(process_id, status=ProcessStatus.ERROR,
                            error_message=f"Lettura del documento fallita: {e}"[:200]):
                db.session.commit()
            return
        extract_info_from_text(process_id, text)


@doc_bp.route('', methods=['POST'])
@jwt_required()
@swag_from({
    'tags': ['Documents'],
    'consumes': ['multipart/form-data'],
    'parameters': [
        {'name': 'files', 'in': 'formData', 'type': 'file', 'required': True,
         'description': 'Uno o più CV PDF (campo ripetuto; accettato anche "file")'},
        {'name': 'title', 'in': 'formData', 'type': 'string', 'required': False,
         'description': 'Usato solo con un file; altrimenti il titolo è il nome del file'},
        {'name': 'metadata', 'in': 'formData', 'type': 'string', 'required': False},
    ],
    'responses': {202: {'description': 'Un processo PENDING per ogni CV'},
                  400: {'description': 'Nessun file o file non PDF'}}
})
def upload():
    user_id = int(get_jwt_identity())
    files = request.files.getlist('files') + request.files.getlist('file')
    if not files:
        return jsonify({'msg': 'Nessun file caricato'}), 400
    not_pdf = [f.filename for f in files if not f.filename.lower().endswith('.pdf')]
    if not_pdf:
        return jsonify({'msg': 'Sono accettati solo PDF', 'files': not_pdf}), 400

    title = request.form.get('title') if len(files) == 1 else None
    metadata = request.form.get('metadata', '')
    os.makedirs(current_app.config['UPLOAD_FOLDER'], exist_ok=True)

    jobs = []
    for file in files:
        data = file.read()
        path = os.path.join(current_app.config['UPLOAD_FOLDER'], f"{uuid.uuid4()}_{secure_filename(file.filename)}")
        with open(path, 'wb') as f:
            f.write(data)
        doc = Document(user_id=user_id, title=title or file.filename, meta_data=metadata, file_path=path, version=1)
        process = Process(user_id=user_id, status=ProcessStatus.PENDING, document=doc)
        db.session.add_all([doc, process])
        jobs.append((process, file.filename, data))
    db.session.commit()

    app = current_app._get_current_object()
    for process, name, data in jobs:
        Thread(target=analyze_file, args=(app, process.id, name, data)).start()
    return jsonify(processes_schema.dump([p for p, _, _ in jobs])), 202


@doc_bp.route('', methods=['GET'])
@jwt_required()
@swag_from({
    'tags': ['Documents'],
    'parameters': [
        {'name': 'title', 'in': 'query', 'type': 'string', 'required': False},
        {'name': 'metadata', 'in': 'query', 'type': 'string', 'required': False},
    ],
    'responses': {200: {'description': 'Storico dei CV (più recenti prima), ognuno con la sua estrazione'}}
})
def get_documents():
    query = Document.query.filter_by(user_id=int(get_jwt_identity()))
    if 'title' in request.args:
        query = query.filter(Document.title.ilike(f"%{request.args['title']}%"))
    if 'metadata' in request.args:
        query = query.filter(Document.meta_data.ilike(f"%{request.args['metadata']}%"))
    documents = query.order_by(Document.created_at.desc(), Document.id.desc()).all()
    return jsonify(history_schema.dump(documents, many=True))


@doc_bp.route('/summary', methods=['GET'])
@jwt_required()
@swag_from({
    'tags': ['Documents'],
    'responses': {200: {'description': "Somma delle estrazioni di tutti i CV COMPLETED dell'utente"}}
})
def get_summary():
    documents = documenti_completati(int(get_jwt_identity()))
    return jsonify(somma_estrazioni([(d.id, d.process.result or {}) for d in documents]))


@doc_bp.route('/<int:doc_id>', methods=['DELETE'])
@jwt_required()
@swag_from({
    'tags': ['Documents'],
    'responses': {200: {'description': 'CV, estrazione e file cancellati (anche se ancora in analisi)'},
                  404: {'description': 'Non trovato'}}
})
def delete_document(doc_id):
    doc = Document.query.filter_by(id=doc_id, user_id=int(get_jwt_identity())).first()
    if not doc:
        return jsonify({'msg': 'Document not found'}), 404
    path = doc.file_path
    Process.query.filter_by(document_id=doc.id).delete()
    db.session.delete(doc)
    db.session.commit()
    try:
        os.remove(path)
    except OSError:
        logging.warning(f"File del CV non rimosso: {path}")
    return jsonify({'msg': 'Document deleted', 'id': doc_id})


@doc_bp.route('/<int:doc_id>', methods=['GET'])
@jwt_required()
@swag_from({
    'tags': ['Documents'],
    'responses': {200: {'description': 'Un CV con la sua estrazione'}, 404: {'description': 'Non trovato'}}
})
def get_document(doc_id):
    doc = Document.query.filter_by(id=doc_id, user_id=int(get_jwt_identity())).first()
    if not doc:
        return jsonify({'msg': 'Document not found'}), 404
    return jsonify(history_schema.dump(doc))


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
        path=file_name,
        as_attachment=True
    )