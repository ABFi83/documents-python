import unittest
from datetime import datetime

from app.services.extract_service import estrai_esperienze_generico, estrai_ruolo_obiettivo, estrai_skill, parse_date

# Testo come esce da PyPDF2 per un CV reale (contatti rimossi)
CV = """Alessio Baldini
Senior Python Engineer · Backend, Microservizi & Sistemi Distribuiti
PROFILO
Ingegnere del software con 15+ anni di esperienza in sistemi distribuiti.
COMPETENZE
Python & backend: Python (FastAPI, Flask, Gunicorn, Celery), API REST,
microservizi, Java/Spring Boot, Kafka, code di job asincroni
Database & performance: PostgreSQL, MongoDB, Redis
AI, frontend, leadership: agenti AI, RAG · Angular, Vue.js, React · team da 5 a 20
persone, mentoring
ESPERIENZA PROFESSIONALE
Product Owner, Lead Architect & Software Engineering Manager — Wilson.ai set 2025 – oggi
40Factory, Firenze · Full remote
Backend Python: API REST e job asincroni con FastAPI.
Technical Lead — GFT Technologies, Firenze gen 2020 – ago 2025
Guida di team da 5 a 20 persone.
Banco BPM: riscrittura del frontend da JSPX a Vue.js.ESPERIENZE PRECEDENTI
Team Leader — Noovle 2018 – 2019
Progetti su Google Cloud.
Software Engineer — TAI Software Solutions · CNR 2009 – 2015
Portlet Liferay per Regione Toscana.
PROGETTI PERSONALI
Progetto full-stack con agenti LLM (Python/FastAPI, Angular/React, Docker).
FORMAZIONE E LINGUE
Laurea Triennale in Informatica, Università degli Studi di Firenze, 2002–2005
"""


class ExtractServiceTestCase(unittest.TestCase):
    def test_ruolo_obiettivo_from_headline(self):
        self.assertEqual(estrai_ruolo_obiettivo(CV), 'Senior Python Engineer')

    def test_ruolo_obiettivo_missing(self):
        self.assertIsNone(estrai_ruolo_obiettivo("Mario Rossi\nPROFILO\nqualcosa\n"))

    def test_skill_section_without_tecniche(self):
        linguaggi, frameworks = estrai_skill(CV)
        self.assertEqual(sorted(linguaggi), ['Java', 'Python'])
        self.assertEqual(sorted(frameworks), ['Angular', 'React', 'Spring Boot', 'Vue.js'])

    def test_experiences_role_dash_company_italian_dates(self):
        esp = estrai_esperienze_generico(CV)
        self.assertEqual(
            [(e['ruolo'], e['azienda'], e['start_date'], e['end_date']) for e in esp],
            [
                ('Product Owner, Lead Architect & Software Engineering Manager', 'Wilson.ai',
                 datetime(2025, 9, 1), None),
                ('Technical Lead', 'GFT Technologies, Firenze', datetime(2020, 1, 1), datetime(2025, 8, 1)),
                ('Team Leader', 'Noovle', datetime(2018, 1, 1), datetime(2019, 1, 1)),
                ('Software Engineer', 'TAI Software Solutions · CNR', datetime(2009, 1, 1), datetime(2015, 1, 1)),
            ],
        )
        self.assertTrue(esp[0]['description'].startswith('40Factory, Firenze'))
        # la sezione PROGETTI PERSONALI non finisce nella descrizione
        self.assertNotIn('PROGETTI', esp[3]['description'])

    def test_old_format_still_works(self):
        text = "COMPETENZE TECNICHE\nPHP, Laravel\nESPERIENZE\nAcme Srl 01/2020 - present\nsviluppatore\nfatto cose\n"
        self.assertEqual(estrai_skill(text), (['Php'], ['Laravel']))
        esp = estrai_esperienze_generico(text)
        self.assertEqual(len(esp), 1)
        self.assertEqual((esp[0]['azienda'], esp[0]['ruolo'], esp[0]['description']),
                         ('Acme Srl', 'Sviluppatore', 'fatto cose'))
        self.assertEqual(esp[0]['start_date'], datetime(2020, 1, 1))
        self.assertIsNone(esp[0]['end_date'])

    def test_parse_date(self):
        self.assertEqual(parse_date('settembre 2025'), datetime(2025, 9, 1))
        self.assertIsNone(parse_date('Oggi'))
        self.assertIsNone(parse_date('boh'))


if __name__ == '__main__':
    unittest.main()
