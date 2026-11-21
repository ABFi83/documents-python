import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

from app import create_app, db
from app.models import Position, PositionEvent
from app.services.agent.pages import PageError
from tests.fakes import FakeLlm, register_fakes, reset_fakes

REPLY = {'titolo': 'Dev Python', 'azienda': 'Acme', 'luogo': 'Milano', 'modalita': None,
         'descrizione': 'desc', 'requisiti': 'req', 'data_pubblicazione': None, 'fonte': None}
URL = 'https://jobs.example.com/a'


class ManualPositionTestCase(unittest.TestCase):
    def setUp(self):
        register_fakes()
        reset_fakes()
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'ENCRYPTION_KEY': Fernet.generate_key().decode()})
        self.client = self.app.test_client()
        self.client.post('/auth/register', json={'username': 'u', 'password': 'p'})
        token = self.client.post('/auth/login', json={'username': 'u', 'password': 'p'}).get_json()['access_token']
        self.auth = {'Authorization': f'Bearer {token}'}
        FakeLlm.json_reply = dict(REPLY)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def llm_on(self):
        self.client.post('/settings/connections', headers=self.auth,
                         json={'kind': 'llm', 'provider': 'fake', 'model': 'fake-1', 'api_key': 'x'})

    def post(self, body='default', **kw):
        return self.client.post('/positions/manual', json=kw if body == 'default' else body, headers=self.auth)

    def test_url_ok(self):
        self.llm_on()
        with patch('app.routes.positions.read_page', return_value='testo pagina'):
            r = self.post(url=URL, stato_iniziale='da_valutare')
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        d = r.get_json()
        self.assertEqual((d['titolo'], d['azienda'], d['origine'], d['stato'], d['url']),
                         ('Dev Python', 'Acme', 'manuale', 'da_valutare', URL))
        self.assertEqual(d['fonte'], 'jobs.example.com')

    def test_default_candidato_needs_vote(self):
        self.llm_on()
        r = self.post(url=URL)
        self.assertEqual(r.status_code, 409)

    def test_candidato_with_vote_and_event(self):
        self.llm_on()
        r = self.post(testo='annuncio', stato_iniziale='candidato', interesse=4)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()['stato'], 'candidato')
        with self.app.app_context():
            ev = PositionEvent.query.one()
            self.assertEqual((ev.da_stato, ev.a_stato, ev.interesse, ev.nota),
                             (None, 'candidato', 4, 'inserimento manuale'))

    def test_page_unreadable(self):
        self.llm_on()
        with patch('app.routes.positions.read_page', side_effect=PageError('x')):
            r = self.post(url=URL, stato_iniziale='da_valutare')
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.get_json()['code'], 'pagina_non_leggibile')

    def test_duplicate(self):
        self.llm_on()
        first = self.post(testo='a', stato_iniziale='da_valutare').get_json()
        r = self.post(testo='b', stato_iniziale='da_valutare')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()['duplicato'])
        self.assertEqual(r.get_json()['id'], first['id'])
        with self.app.app_context():
            self.assertEqual(Position.query.count(), 1)
            self.assertEqual(PositionEvent.query.count(), 1)

    def test_validation(self):
        self.assertEqual(self.post(stato_iniziale='da_valutare').status_code, 400)  # niente url/testo
        self.assertEqual(self.post(testo='a', stato_iniziale='da_valutare').status_code, 400)  # niente LLM
        self.assertEqual(self.post(body=[1]).status_code, 400)
        self.assertEqual(self.post(testo=5).status_code, 400)
        self.llm_on()
        self.assertEqual(self.post(testo='a', stato_iniziale='boh').status_code, 400)
        for v in (0, 6, True, '3'):
            self.assertEqual(self.post(testo='a', interesse=v).status_code, 400)

    def test_extraction_failures(self):
        self.llm_on()
        FakeLlm.json_reply = {'titolo': '', 'azienda': 'Acme'}
        r = self.post(testo='a', stato_iniziale='da_valutare')
        self.assertEqual((r.status_code, r.get_json()['code']), (422, 'estrazione_fallita'))
        FakeLlm.json_reply = 'non un dict'
        self.assertEqual(self.post(testo='a', stato_iniziale='da_valutare').status_code, 422)

    def test_adapter_error(self):
        self.llm_on()
        from app.services.ai.base import AdapterError
        with patch.object(FakeLlm, 'extract_json', side_effect=AdapterError('giu')):
            r = self.post(testo='a', stato_iniziale='da_valutare')
        self.assertEqual((r.status_code, r.get_json()['code']), (502, 'ai_non_disponibile'))

    def test_text_truncated(self):
        self.llm_on()
        seen = []
        orig = FakeLlm.extract_json
        with patch.object(FakeLlm, 'extract_json', lambda s, p, sc: (seen.append(p), orig(s, p, sc))[1]):
            self.post(testo='x' * 30000, stato_iniziale='da_valutare')
        self.assertLess(len(seen[0]), 21000)


if __name__ == '__main__':
    unittest.main()
