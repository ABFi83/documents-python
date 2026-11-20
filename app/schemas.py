from app import ma
from app.models import Process, User, Skill, Experience, Document
from marshmallow import fields

Schema = ma.Schema  # adds .jsonify()

class SkillSchema(Schema):
    id = fields.Int()
    name = fields.Str()
    level = fields.Str()

class ExperienceSchema(Schema):
    id = fields.Int()
    company_name = fields.Str()
    role = fields.Str()
    start_date = fields.Str(allow_none=True)
    end_date = fields.Str(allow_none=True)
    description = fields.Str(allow_none=True)
    is_current = fields.Boolean(allow_none=True)

class DocumentSchema(Schema):
    id = fields.Int()
    title = fields.Str()
    meta_data = fields.Str()
    file_path = fields.Str()
    version = fields.Int()
    created_at = fields.DateTime()

class UserSchema(Schema):
    id = fields.Int()
    name = fields.Str()
    surname = fields.Str()
    username = fields.Str()
    skill = fields.Nested(SkillSchema, many=True)
    experience = fields.Nested(ExperienceSchema, many=True)
    documents = fields.Nested(DocumentSchema, many=True)
   

class ProcessSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = Process
        load_instance = True