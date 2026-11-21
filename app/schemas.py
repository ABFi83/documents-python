from app import ma
from app.models import Process
from marshmallow import fields, validate

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


class CompetenzaSchema(ma.Schema):
    nome = fields.Str(required=True, validate=validate.Length(min=1))
    obbligatoria = fields.Boolean(load_default=False)


class CriteriaSchema(ma.Schema):
    ruoli = fields.List(fields.Str(), load_default=list)
    competenze = fields.List(fields.Nested(CompetenzaSchema), load_default=list)
    luogo = fields.Str(allow_none=True, load_default=None)
    modalita = fields.List(fields.Str(validate=validate.OneOf(['remoto', 'ibrido', 'presenza'])), load_default=list)
    seniority = fields.Str(allow_none=True, load_default=None)
    contratto = fields.Str(allow_none=True, load_default=None)
    ral_min = fields.Int(allow_none=True, load_default=None)
    lingue = fields.List(fields.Str(), load_default=list)
    esclusioni = fields.List(fields.Str(), load_default=list)
    max_giorni_annuncio = fields.Int(load_default=30)
    note = fields.Str(allow_none=True, load_default=None)


class SearchProfileSchema(ma.Schema):
    id = fields.Int(dump_only=True)
    name = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    criteria = fields.Nested(CriteriaSchema, load_default=lambda: CriteriaSchema().load({}))
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
