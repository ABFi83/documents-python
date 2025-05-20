import logging
from datetime import datetime
from app import db
from app.models import Process, User, Skill, Experience, ProcessStatus
import spacy
import re

nlp = spacy.load("it_core_news_sm")

def extract_info_from_text(process: Process, text: str):
    info = {
        "nome": None,
        "cognome": None,
        "linguaggi": [],
        "frameworks": [],
        "esperienze": []
    }
    try:
        user = User.query.get(process.user_id)
        if not user:
            raise ValueError("Utente non trovato")
        doc = nlp(text)
        # === 1. Nome e Cognome (prima entità PERSON) ===
        for ent in doc.ents:
            if ent.label_ == "PER":
                nome_cognome = ent.text.strip().split()
                if len(nome_cognome) >= 2:
                    info["nome"] = nome_cognome[0]
                    info["cognome"] = " ".join(nome_cognome[1:])
                elif len(nome_cognome) == 1:
                    info["nome"] = nome_cognome[0]
                break
        if info["nome"]:
            user.name = info["nome"]
        if info["cognome"]:
            user.surname = info["cognome"]
        # === 2. Skill Tecniche: regex su sezione COMPETENZE TECNICHE ===
        skill_section = re.search(
            r'COMPETENZE[\s_-]?TECNICHE[\s\n\r:]*([\s\S]*?)(?:\n[A-Z][A-Z\s]{3,}|ISTRUZIONE|FORMAZIONE|PROGETTI|ESPERIENZE|$)',
            text
        )
        if skill_section:
            skills_text = skill_section.group(1)
            linguaggi = re.findall(r'\b(Java|Python|JavaScript|SQL|C\+\+|C#|PHP|HTML|CSS)\b', skills_text, re.IGNORECASE)
            frameworks = re.findall(r'\b(Spring Boot|Angular|React|Vue\.js|Django|Laravel|.NET|Node\.js|Google Suite)\b', skills_text, re.IGNORECASE)
            info["linguaggi"] = list(set(map(str.capitalize, linguaggi)))
            info["frameworks"] = list(set(map(str.strip, frameworks)))
     
        if info["linguaggi"]:
            for lang in info["linguaggi"]:
                skill = Skill(name=lang, level=None, user_id=user.id)
                db.session.add(skill)
        if info["frameworks"]:
            for fw in info["frameworks"]:
                skill = Skill(name=fw, level=None, user_id=user.id)
                db.session.add(skill)

                
        # === 3. Esperienze: estrai solo la sezione che inizia con ESPERIENZE ===
        esperienze_section = re.search(
            r'ESPERIENZE[\s\n\r:]*([\s\S]*?)(?:\n[A-Z][A-Z\s]{3,}|ISTRUZIONE|FORMAZIONE|PROGETTI|COMPETENZE|$)',
            text, re.IGNORECASE
        )
        aziende = []
        ruoli = []
        if esperienze_section:
            esperienze_text = esperienze_section.group(1)
            aziende = re.findall(r'([A-Z][A-Za-z0-9&.\- ]+)', esperienze_text)
            ruoli = re.findall(r'(Technical Lead|Team Leader|Software Developer|Solution Engineer)', esperienze_text, re.IGNORECASE)
        else:
            aziende = [ent.text.strip() for ent in doc.ents if ent.label_ == "ORG"]
            ruoli = re.findall(r'(Technical Lead|Team Leader|Software Developer|Solution Engineer)', text, re.IGNORECASE)
        for i in range(min(len(aziende), len(ruoli))):
            info["esperienze"].append({
                "azienda": aziende[i],
                "ruolo": ruoli[i].title()
            })
        # Salvataggio esperienze lavorative
        if info["esperienze"]:
            for exp in info["esperienze"]:
                experience = Experience(
                    company_name=exp["azienda"],
                    role=exp["ruolo"],
                    start_date=None,
                    end_date=None,
                    description=None,
                    user_id=user.id
                )
                db.session.add(experience) 
        process.status = ProcessStatus.COMPLETED
    except Exception as e:
        logging.error(f"[Estrazione fallita] {str(e)}")
        process.status = ProcessStatus.ERROR
        process.error_message = str(e)
        info['error'] = str(e)   
        try:
            db.session.add(process)
            db.session.commit()
        except Exception as db_exc:
            logging.error(f"[Salvataggio processo fallito] {str(db_exc)}")
        return info
    finally:
        process.end_end_time = datetime.now()
        try:
            db.session.add(user)
            db.session.commit()
        except Exception as user_exc:
            logging.error(f"[Salvataggio user/relazioni fallito] {str(user_exc)}")
            db.session.rollback()
            process.status = ProcessStatus.ERROR
            process.error_message = str(user_exc)
            info['error'] = str(user_exc)
        try:
            logging.debug(f"[Salvataggio processo] ID: {process.id} - Status: {process.status}")
            db.session.add(process)
            db.session.commit()
        except Exception as db_exc:
            logging.error(f"[Salvataggio processo fallito] {str(db_exc)}")
            db.session.rollback()
    logging.debug(f"[Estrazione completata] Process ID: {process.id} - Info: {info}")
    return info
