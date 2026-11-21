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