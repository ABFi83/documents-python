from app import ma
from app.models import Process
from marshmallow import fields

class SkillSchema(ma.Schema):
    id = fields.Int()
    name = fields.Str()
    level = fields.Str()

class ExperienceSchema(ma.Schema):
    id = fields.Int()
    company_name = fields.Str()
    role = fields.Str()
    start_date = fields.Str(allow_none=True)
    end_date = fields.Str(allow_none=True)
    description = fields.Str(allow_none=True)
    is_current = fields.Boolean(allow_none=True)

class DocumentSchema(ma.Schema):
    id = fields.Int()
    title = fields.Str()
    meta_data = fields.Str()
    file_path = fields.Str()
    version = fields.Int()
    created_at = fields.DateTime()

class UserSchema(ma.Schema):
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