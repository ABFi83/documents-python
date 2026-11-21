import logging
import os
from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from flask_jwt_extended import JWTManager
from flasgger import Swagger
from flask_cors import CORS

db = SQLAlchemy()
ma = Marshmallow()
jwt = JWTManager()


def create_app(config=None):

    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    app = Flask(__name__)
    CORS(app)  # Enable CORS for the entire application
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite'
    app.config['UPLOAD_FOLDER'] = 'uploads'
    app.config['DOCLING_URL'] = os.environ.get('DOCLING_URL', 'http://localhost:5001')
    app.config['ENCRYPTION_KEY'] = os.environ.get('ENCRYPTION_KEY')
    app.config['JWT_SECRET_KEY'] = 'super-secret-key'
    app.config['SWAGGER'] = {'title': 'Document API', 'uiversion': 3}
    # limiti per run dell'agente
    app.config['AGENT_MAX_STEPS'] = 30
    app.config['AGENT_MAX_SEARCHES'] = 15
    app.config['AGENT_MAX_PAGES'] = 25
    app.config['AGENT_MAX_SAVED'] = 20
    app.config.update(config or {})

    db.init_app(app)
    ma.init_app(app)
    jwt.init_app(app)
    Swagger(app)

    @app.before_request
    def log_request_info():
        logging.info(f"Request: {request.method} {request.url}")
        logging.info(f"Headers: {request.headers}")
        # le chiavi API passano da /settings: il body non va mai nei log
        body = '<omesso>' if request.path.startswith('/settings') else request.get_data()
        logging.info(f"Body: {body}")

    from app.routes.auth import auth_bp
    from app.routes.documents import doc_bp
    from app.routes.user import user_bp
    from app.routes.process import proc_bp
    from app.routes.settings import settings_bp
    from app.routes.search_profiles import sp_bp
    from app.routes.positions import pos_bp
    from app.routes.runs import runs_bp
    app.register_blueprint(runs_bp, url_prefix='/runs')
    app.register_blueprint(pos_bp, url_prefix='/positions')
    app.register_blueprint(sp_bp, url_prefix='/search-profiles')
    app.register_blueprint(settings_bp, url_prefix='/settings')
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(doc_bp, url_prefix='/documents')
    app.register_blueprint(user_bp, url_prefix='/users')
    app.register_blueprint(proc_bp, url_prefix='/process')
    
    with app.app_context():
        db.create_all()
        # create_all non aggiunge indici a tabelle già esistenti (niente migrazioni)
        from app.models import SearchRun
        for index in SearchRun.__table__.indexes:
            index.create(db.engine, checkfirst=True)

    return app