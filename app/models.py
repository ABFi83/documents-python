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

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(100))
    meta_data = db.Column(db.String(200))
    file_path = db.Column(db.String(200))
    version = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Process(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(Enum(ProcessStatus), default=ProcessStatus.PENDING)  # Use Enum for status
    start_end = db.Column(db.DateTime, default=datetime.utcnow)
    end_end = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.String(200), nullable=True)