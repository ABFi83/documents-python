from app import db
from datetime import datetime
from sqlalchemy import Enum
import enum

class ProcessStatus(enum.Enum):
    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    ERROR = 'error'

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True)
    password = db.Column(db.String(200))
    name= db.Column(db.String(200))
    surname= db.Column(db.String(200))
    documents = db.relationship('Document', backref='owner', lazy=True)
    process = db.relationship('Process', backref='user', lazy=True)
    skill = db.relationship('Skill', backref='user', lazy=True)
    experience = db.relationship('Experience', backref='user', lazy=True)

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(100))
    meta_data = db.Column(db.String(200))
    file_path = db.Column(db.String(200))
    version = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    process = db.relationship('Process', backref='document', uselist=False)

class Process(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=True)
    status = db.Column(Enum(ProcessStatus), default=ProcessStatus.PENDING)  # Use Enum for status
    start_date = db.Column(db.DateTime, default=datetime.utcnow)
    end_date = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.String(200), nullable=True)
    # estrazione del CV: {nome, cognome, linguaggi, frameworks, esperienze}; non tocca il profilo utente
    result = db.Column(db.JSON, nullable=True)

class Skill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    level = db.Column(db.String(50), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Experience(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(100), nullable=True)
    start_date = db.Column(db.String(30), nullable=True)
    end_date = db.Column(db.String(30), nullable=True)
    description = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_current = db.Column(db.Boolean, default=False)

class AiConnection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    kind = db.Column(db.String(10), nullable=False)  # 'llm' | 'search'
    provider = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(100), nullable=True)
    api_key_enc = db.Column(db.Text, nullable=False)  # mai restituita dalle API
    key_last4 = db.Column(db.String(4), nullable=False)
    active = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class SearchProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    criteria = db.Column(db.JSON, nullable=False)  # validato da CriteriaSchema
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Position(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    run_id = db.Column(db.Integer, nullable=True)  # null se manuale; FK con SearchRun (Task 10)
    profile_id = db.Column(db.Integer, db.ForeignKey('search_profile.id'), nullable=True)
    url = db.Column(db.String(2000))
    url_norm = db.Column(db.String(2000), index=True)
    key_norm = db.Column(db.String(500), index=True)
    titolo = db.Column(db.String(200))
    azienda = db.Column(db.String(200))
    luogo = db.Column(db.String(200))
    modalita = db.Column(db.String(30))
    descrizione = db.Column(db.Text)
    requisiti = db.Column(db.Text)
    data_pubblicazione = db.Column(db.String(30))
    fonte = db.Column(db.String(200))
    punteggio_ai = db.Column(db.Integer)  # 0-100
    motivazione_ai = db.Column(db.Text)
    skill_presenti = db.Column(db.JSON)
    skill_mancanti = db.Column(db.JSON)
    origine = db.Column(db.String(10), nullable=False, default='manuale')  # 'agente' | 'manuale'
    stato = db.Column(db.String(20), nullable=False, default='da_valutare')
    interesse = db.Column(db.Integer, nullable=True)  # 1-5
    motivo = db.Column(db.Text)
    motivo_tipo = db.Column(db.String(20))  # generico | annuncio | preferenza
    motivo_preferenza = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, **kw):
        from app.services.positions import normalize_url, normalize_key
        if kw.get('url'):
            kw.setdefault('url_norm', normalize_url(kw['url']))
        kw.setdefault('key_norm', normalize_key(kw.get('azienda') or '', kw.get('titolo') or ''))
        super().__init__(**kw)


class PositionEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    position_id = db.Column(db.Integer, db.ForeignKey('position.id'), nullable=False, index=True)
    da_stato = db.Column(db.String(20))
    a_stato = db.Column(db.String(20))
    interesse = db.Column(db.Integer)
    nota = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
