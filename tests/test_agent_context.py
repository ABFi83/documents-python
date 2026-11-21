import json
from datetime import date
import unittest

from app import create_app, db
from app.models import Document, Position, Process, ProcessStatus, SearchProfile, User
from app.services.agent.context import build_feedback, profile_context
from app.services.agent.prompt import SYSTEM_PROMPT, initial_message


class AgentContextTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.session.add(User(username='u', password='p'))
        db.session.add_all([SearchProfile(user_id=1, name='a', criteria={}),
                            SearchProfile(user_id=1, name='b', criteria={})])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def cv(self, result, status=ProcessStatus.COMPLETED):
        d = Document(user_id=1, title='cv')
        db.session.add(d)
        db.session.flush()
        db.session.add(Process(user_id=1, document_id=d.id, status=status, result=result))
        db.session.commit()

    def pos(self, n, profile_id=1, **kw):
        db.session.add(Position(user_id=1, url=f'https://x.it/{n}', titolo=f't{n}', azienda=f'a{n}',
                                profile_id=profile_id, **kw))
        db.session.commit()

    def test_profile_no_personal_data(self):
        self.cv({'nome': 'Mario', 'cognome': 'Rossi', 'ruolo_obiettivo': 'Dev',
                 'linguaggi': ['Python'], 'frameworks': ['Flask'],
                 'esperienze': [{'azienda': 'Acme', 'ruolo': 'Dev mario@example.com', 'start_date': '2019-03',
                                 'end_date': None, 'description': 'scrivo a mario@example.com'}]})
        p = profile_context(1)
        s = json.dumps(p)
        for x in ('Mario', 'Rossi', '@', 'description'):
            self.assertNotIn(x, s)
        self.assertIn('Acme', s)
        self.assertEqual(p['skill'], ['Python', 'Flask'])
        self.assertEqual(p['ruoli_obiettivo'], ['Dev'])
        self.assertGreaterEqual(p['anni_esperienza'], 7)

    def test_ruoli_con_nome_scartati(self):
        # CV estratti prima del fix: ruolo_obiettivo può essere il nome o un pezzo di esso
        user = db.session.get(User, 1)
        user.name, user.surname = 'Anna', 'Bianchi'
        self.cv({'nome': 'Mario', 'cognome': 'Rossi', 'ruolo_obiettivo': 'Rossi',
                 'esperienze': [{'azienda': 'Acme', 'ruolo': 'Assistente di Anna Bianchi', 'start_date': None}]})
        self.cv({'ruolo_obiettivo': 'Mario Rossi', 'esperienze': []})
        self.cv({'ruolo_obiettivo': 'Data Engineer', 'esperienze': []})
        p = profile_context(1)
        s = json.dumps(p)
        for x in ('Mario', 'Rossi', 'Anna', 'Bianchi'):
            self.assertNotIn(x, s)
        self.assertEqual(p['ruoli_obiettivo'], ['Data Engineer'])

    def test_profile_empty(self):
        self.cv({'linguaggi': [], 'frameworks': [], 'esperienze': []}, ProcessStatus.ERROR)
        self.assertIsNone(profile_context(1)['anni_esperienza'])

    def test_examples_weights(self):
        self.pos(1, stato='promossa', interesse=5)
        self.pos(2, interesse=4, profile_id=2)
        self.pos(3, stato='accettato', interesse=2)
        self.pos(4, interesse=1)
        self.pos(5, stato='non_candidato', interesse=2)
        self.pos(6, stato='rifiutato', interesse=5)
        self.pos(7, interesse=3)
        f = build_feedback(1, 1)
        pos = {e['titolo']: e['peso'] for e in f['positivi']}
        neg = {e['titolo']: e['peso'] for e in f['negativi']}
        self.assertEqual(pos, {'t3': 1.5, 't1': 1.0, 't2': 0.3})
        self.assertEqual(neg, {'t4': 1.0, 't5': 0.3})
        self.assertEqual([e['titolo'] for e in f['positivi']][0], 't3')
        self.assertEqual(len(f['url_gia_visti']), 7)  # anche rifiutato

    def test_preferences(self):
        self.pos(1, interesse=1, motivo_tipo='preferenza', motivo_preferenza='Niente Viaggi')
        self.pos(2, interesse=1, motivo_tipo='preferenza', motivo_preferenza='niente viaggi')
        self.pos(3, interesse=1, motivo_tipo='preferenza', motivo_preferenza='no turni', profile_id=2)
        self.pos(4, interesse=1, motivo_tipo='generico', motivo_preferenza='ignora')
        self.pos(5, interesse=1, motivo_tipo='annuncio', motivo_preferenza='ignora')
        self.pos(6, stato='rifiutato', interesse=1, motivo_tipo='preferenza', motivo_preferenza='no Milano')
        pref = {p['testo']: p['peso'] for p in build_feedback(1, 1)['preferenze_da_evitare']}
        self.assertEqual(pref, {'Niente Viaggi': 1.5, 'no turni': 0.5})  # rifiutato: motivo non è una preferenza

    def test_prompt(self):
        m = initial_message({'ruoli': ['Dev'], 'max_giorni_annuncio': 7}, {'skill': []}, {'positivi': []})
        self.assertIn('Dev', m)
        self.assertEqual(m, initial_message({'ruoli': ['Dev'], 'max_giorni_annuncio': 7}, {'skill': []}, {'positivi': []}))
        self.assertIn('Data di oggi: 2026-01-02', initial_message({}, {}, {}, oggi=date(2026, 1, 2)))
        self.assertNotIn('Data di oggi', SYSTEM_PROMPT)
        for t in ('cerca_web', 'leggi_pagina', 'salva_posizione', 'fai_domanda', 'url_gia_visti', 'max_giorni_annuncio'):
            self.assertIn(t, SYSTEM_PROMPT)


if __name__ == '__main__':
    unittest.main()
