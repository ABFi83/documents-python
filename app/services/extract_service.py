import logging
from datetime import datetime
from app import db
from app.models import Process, User, ProcessStatus
import spacy
from sqlalchemy import update
import re

from app.services.summary_service import contiene_nome

nlp = spacy.load("it_core_news_sm")


MESI = {'gen': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'mag': 5, 'giu': 6,
        'lug': 7, 'ago': 8, 'set': 9, 'ott': 10, 'nov': 11, 'dic': 12}

# 09/2025 | set 2025 | settembre 2025 | 2025
DATA = r'(?:\d{1,2}/\d{4}|(?:' + '|'.join(MESI) + r')[a-z]*\.?\s+\d{4}|\d{4})'
FINE = DATA + r'|present|oggi|attuale'
# "<intestazione> <inizio> - <fine>" su una riga; trattino normale, en o em dash
HEADER = re.compile(
    r'^(?P<head>.+?)\s+(?P<start>' + DATA + r')\s*[-–—]\s*(?P<end>' + FINE + r')\s*$',
    re.IGNORECASE | re.MULTILINE,
)
# riga tutta maiuscola = intestazione di sezione (es. "ESPERIENZA PROFESSIONALE")
SEZIONE = re.compile(r'^[A-ZÀ-Ý][A-ZÀ-Ý &]{3,}$')


def parse_date(date_str):
    s = date_str.strip().lower()
    if s in ('present', 'oggi', 'attuale'):
        return None
    try:
        if re.fullmatch(r'\d{1,2}/\d{4}', s):
            return datetime.strptime(s, "%m/%Y")
        if re.fullmatch(r'\d{4}', s):
            return datetime(int(s), 1, 1)
        mese, anno = s.split()
        return datetime(int(anno), MESI[mese[:3]], 1)
    except Exception:
        return None


def estrai_esperienze_generico(text):
    """
    Estrae le esperienze dalle righe "<intestazione> <data> - <data|oggi>".
    Intestazione "Ruolo — Azienda" (o "Ruolo - Azienda"), altrimenti solo azienda e ruolo sulla riga dopo.
    """
    # le date della formazione ("Laurea ..., 2002–2005") non sono esperienze
    formazione = re.search(r'^(?:FORMAZIONE|ISTRUZIONE|EDUCATION)\b', text, re.MULTILINE)
    if formazione:
        text = text[:formazione.start()]

    headers = list(HEADER.finditer(text))
    esperienze = []
    for i, m in enumerate(headers):
        fine_blocco = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        lines = []
        for line in text[m.end():fine_blocco].strip().splitlines():
            if SEZIONE.match(line.strip()):
                break
            lines.append(line.strip())

        head = m.group('head').strip()
        parti = re.split(r'\s+[—–-]\s+', head, maxsplit=1)
        if len(parti) == 2:
            ruolo, azienda = parti
        else:
            azienda = head
            ruolo = lines.pop(0) if lines else "Ruolo non specificato"

        esperienze.append({
            "azienda": azienda,
            "start_date": parse_date(m.group('start')),
            "end_date": parse_date(m.group('end')),
            "ruolo": ruolo.title(),
            "description": "\n".join(lines).strip() or None,
        })

    return esperienze


def estrai_skill(text):
    """Linguaggi e framework (whitelist) dalla sezione COMPETENZE [TECNICHE]."""
    section = re.search(
        r'COMPETENZE(?:[\s_-]?TECNICHE)?[ \t:]*\n([\s\S]*?)(?=^[A-ZÀ-Ý][A-ZÀ-Ý &]{3,}$|ISTRUZIONE|FORMAZIONE|PROGETTI|ESPERIENZ|\Z)',
        text, re.MULTILINE
    )
    if not section:
        return [], []
    skills_text = section.group(1)
    linguaggi = re.findall(r'\b(Java|Python|JavaScript|SQL|C\+\+|C#|PHP|HTML|CSS)\b', skills_text, re.IGNORECASE)
    frameworks = re.findall(r'\b(Spring Boot|Angular|React|Vue\.js|Django|Laravel|.NET|Node\.js|Google Suite)\b', skills_text, re.IGNORECASE)
    return list(set(map(str.capitalize, linguaggi))), list(set(map(str.strip, frameworks)))


def estrai_nome(text):
    """Prima entità PER di spaCy -> (nome, cognome)."""
    for ent in nlp(text).ents:
        if ent.label_ == "PER":
            parti = ent.text.strip().split()
            if parti:
                return parti[0], " ".join(parti[1:]) or None
    return None, None


# indirizzo: inizia con Via/Viale/Piazza/... oppure contiene un CAP (5 cifre)
INDIRIZZO = re.compile(r'^(?:via|viale|piazza|p\.zza|corso|largo|vicolo|strada)\b|\b\d{5}\b', re.IGNORECASE)


def estrai_ruolo_obiettivo(text, nome=None, cognome=None):
    """Ruolo dalla riga sotto il nome ("Senior Python Engineer · Backend, ..."), None se non c'è.
    Senza nome trovato nel testo non si indovina: qualunque riga potrebbe essere un dato personale."""
    righe = [r.strip() for r in text.splitlines() if r.strip()]
    inizio = next((i for i, r in enumerate(righe[:5]) if contiene_nome(r, (nome, cognome))), None)
    if inizio is None:
        return None
    for riga in righe[inizio + 1:inizio + 4]:
        if SEZIONE.match(riga):
            break  # iniziata una sezione: niente headline
        # ponytail: contatto = '@' o 6+ cifre in tutto; un'intestazione con tanti numeri sfugge
        if ('@' in riga or len(re.sub(r'\D', '', riga)) >= 6 or INDIRIZZO.search(riga)
                or contiene_nome(riga, (nome, cognome))):
            continue
        ruolo = re.split(r'·|\||\s-\s|,', riga)[0].strip()
        return ruolo or None
    return None


def _iso(d):
    return d.date().isoformat() if d else None


def save_process(process_id: int, **values) -> bool:
    """
    UPDATE condizionato del processo, nella transazione corrente (non fa commit).
    False = il processo è stato cancellato (DELETE /documents/<id>) mentre il CV era in analisi:
    la transazione viene annullata e il chiamante non deve scrivere nient'altro.
    Su SQLite l'UPDATE prende il lock di scrittura, quindi una DELETE non può infilarsi prima del commit.
    """
    values.setdefault("end_date", datetime.utcnow())
    updated = db.session.execute(
        update(Process).where(Process.id == process_id).values(**values)
    ).rowcount
    if not updated:
        db.session.rollback()
        logging.info(f"[Processo {process_id} cancellato durante l'analisi] estrazione scartata")
    return bool(updated)


def extract_info_from_text(process_id: int, text: str):
    """
    Estrae nome, skill ed esperienze dal CV e le salva in process.result (storico del CV).
    Nome e cognome aggiornano anche l'utente; skill ed esperienze non toccano il profilo.
    Se il processo non esiste più non scrive nulla e restituisce None.
    """
    try:
        nome, cognome = estrai_nome(text)
        linguaggi, frameworks = estrai_skill(text)
        info = {
            "ruolo_obiettivo": estrai_ruolo_obiettivo(text, nome, cognome),
            "nome": nome,
            "cognome": cognome,
            "linguaggi": linguaggi,
            "frameworks": frameworks,
            "esperienze": [
                {**e, "start_date": _iso(e["start_date"]), "end_date": _iso(e["end_date"])}
                for e in estrai_esperienze_generico(text)
            ],
        }
    except Exception as e:
        logging.error(f"[Estrazione fallita] {e}")
        if not save_process(process_id, status=ProcessStatus.ERROR, error_message=str(e)[:200]):
            return None
        db.session.commit()
        return {"error": str(e)}

    # prima il processo (lock + controllo che esista), poi l'utente, un solo commit
    if not save_process(process_id, status=ProcessStatus.COMPLETED, result=info):
        return None
    user = db.session.get(User, db.session.get(Process, process_id).user_id)
    if nome:
        user.name = nome
    if cognome:
        user.surname = cognome
    db.session.commit()
    logging.debug(f"[Estrazione completata] Process ID: {process_id}")
    return info
