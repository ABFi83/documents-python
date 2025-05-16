import logging
from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from flask_jwt_extended import JWTManager
from flasgger import Swagger
from flask_cors import CORS
# Removed SocketIO import
import os

db = SQLAlchemy()
ma = Marshmallow()
jwt = JWTManager()


def create_app():

    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    app = Flask(__name__)
    CORS(app)  # Enable CORS for the entire application
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite'
    app.config['UPLOAD_FOLDER'] = 'uploads'
    app.config['JWT_SECRET_KEY'] = 'super-secret-key'
    app.config['SWAGGER'] = {'title': 'Document API', 'uiversion': 3}

    db.init_app(app)
    ma.init_app(app)
    jwt.init_app(app)
    Swagger(app)

    @app.before_request
    def log_request_info():
        logging.info(f"Request: {request.method} {request.url}")
        logging.info(f"Headers: {request.headers}")
        logging.info(f"Body: {request.get_data()}")

    from app.routes.auth import auth_bp
    from app.routes.documents import doc_bp
    from app.routes.user import user_bp
    from app.routes.process import proc_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(doc_bp, url_prefix='/documents')
    app.register_blueprint(user_bp, url_prefix='/users')
    app.register_blueprint(proc_bp, url_prefix='/process')
    
    with app.app_context():
        db.create_all()

    return app