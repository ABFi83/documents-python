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


class ProcessSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = Process
        load_instance = True
        include_fk = True


class DocumentHistorySchema(DocumentSchema):
    process = fields.Nested(ProcessSchema, allow_none=True)

class UserSchema(ma.Schema):
    id = fields.Int()
    name = fields.Str()
    surname = fields.Str()
    username = fields.Str()
    skill = fields.Nested(SkillSchema, many=True)
    experience = fields.Nested(ExperienceSchema, many=True)
    documents = fields.Nested(DocumentSchema, many=True)


class AiConnectionSchema(ma.Schema):
    # niente api_key_enc: la chiave non esce mai
    id = fields.Int()
    kind = fields.Str()
    provider = fields.Str()
    model = fields.Str(allow_none=True)
    key_last4 = fields.Str()
    active = fields.Boolean()
    created_at = fields.DateTime()
