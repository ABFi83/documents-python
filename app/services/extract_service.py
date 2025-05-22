import logging
from datetime import datetime
from typing import Dict, List
from app import db
from app.models import Process, User, Skill, Experience, ProcessStatus
import spacy
import re

nlp = spacy.load("it_core_news_sm")


def parse_date(date_str):
    if date_str.lower() == 'present':
        return None
    try:
        return datetime.strptime(date_str, "%m/%Y")
    except Exception:
        return None


def estrai_esperienze_generico(text):
    """
    Estrae esperienze lavorative da un testo in modo generico.
    """
    esperienze = []

    # Identifica la sezione delle esperienze
    match = re.search(
        r'(ESPERIENZE|WORK EXPERIENCE|EXPERIENCES)[\s\n\r:]*([\s\S]*?)(?=\n[A-Z\s]{3,}|ISTRUZIONE|EDUCATION|FORMAZIONE|$)',
        text, re.IGNORECASE
    )
  
    print("DEBUG: Nessuna sezione ESPERIENZE trovata")
    # Fallback: cerca pattern di date e aziende direttamente nel testo
    esperienze_text = "\n".join(re.findall(
        r'[A-Za-z &.\-\d]+\s+\d{1,2}/\d{4}\s*-\s*(?:present|oggi|\d{1,2}/\d{4})',
        text, re.IGNORECASE
    ))


    print("DEBUG: esperienze_text =", esperienze_text)

    # Dividi in blocchi basati su pattern di date
    blocchi = re.split(
        r'\n(?=[A-Za-z &.\-\d]+\s+\d{1,2}/\d{4}\s*-\s*(?:present|oggi|\d{1,2}/\d{4}))',
        esperienze_text, flags=re.IGNORECASE
    )
    if len(blocchi) == 1:  # Fallback per esperienze su una sola riga
        blocchi = esperienze_text.splitlines()

    for blocco in blocchi:
        if not blocco.strip():
            continue

        print("DEBUG: Blocco =", blocco)

        # Cerca header con azienda, date e ruolo
        header_match = re.match(
            r'([\w &.\-\d]+)\s+(\d{1,2}/\d{4})\s*-\s*(present|oggi|\d{1,2}/\d{4})',
            blocco, re.IGNORECASE
        )
        if not header_match:
            print("DEBUG: No header match for blocco")
            continue

        azienda = header_match.group(1).strip()
        start_date = parse_date(header_match.group(2))
        end_date = parse_date(header_match.group(3))

        # Estrai ruolo e descrizione
        resto = blocco[header_match.end():].strip()
        lines = resto.splitlines()
        ruolo = lines[0].strip() if lines else "Ruolo non specificato"
        descrizione = "\n".join(lines[1:]).strip() if len(lines) > 1 else None

        esperienze.append({
            "azienda": azienda,
            "start_date": start_date,
            "end_date": end_date,
            "ruolo": ruolo.title(),
            "description": descrizione
        })

    return esperienze

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
        experiences = estrai_esperienze_generico(text)

        for exp in experiences:
            experience = Experience(
                company_name=exp['azienda'],
                role=exp['ruolo'],
                start_date=exp['start_date'],
                end_date=exp['end_date'],
                description=exp['description'],
                user_id=user.id
            )
            db.session.add(experience)
            print(f"{exp['azienda']} | {exp['ruolo']} | {exp['start_date']} - {exp['end_date']}")
            print(f"Descrizione: {exp['description']}\n")


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
