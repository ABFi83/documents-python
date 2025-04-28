import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from flask_jwt_extended import JWTManager
from flasgger import Swagger
import os

db = SQLAlchemy()
ma = Marshmallow()
jwt = JWTManager()

def create_app():

    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite'
    app.config['UPLOAD_FOLDER'] = 'uploads'
    app.config['JWT_SECRET_KEY'] = 'super-secret-key'
    app.config['SWAGGER'] = {'title': 'Document API', 'uiversion': 3}

    db.init_app(app)
    ma.init_app(app)
    jwt.init_app(app)
    Swagger(app)

    from app.routes.auth import auth_bp
    from app.routes.documents import doc_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(doc_bp, url_prefix='/documents')

    with app.app_context():
        db.create_all()

    return app