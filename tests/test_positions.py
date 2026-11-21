import unittest

from cryptography.fernet import Fernet

from app import create_app, db
from app.models import Position, PositionEvent
from app.services.positions import find_duplicate, normalize_url, normalize_key, classify_reason
from tests.fakes import FakeLlm, register_fakes, reset_fakes


class PositionsTestCase(unittest.TestCase):
    def setUp(self):
        register_fakes()
        reset_fakes()
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'ENCRYPTION_KEY': Fernet.generate_key().decode()})
        self.client = self.app.test_client()
        self.auth = self.login('u')

    def login(self, name):
        self.client.post('/auth/register', json={'username': name, 'password': 'p'})
        token = self.client.post('/auth/login', json={'username': name, 'password': 'p'}).get_json()['access_token']
        return {'Authorization': f'Bearer {token}'}

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def make(self, user_id=1, **kw):
        with self.app.app_context():
            p = Position(user_id=user_id, url='https://x.it/a', titolo='Dev', azienda='Acme', origine='manuale', **kw)
            db.session.add(p)
            db.session.commit()
            return p.id

    def llm_on(self):
        self.client.post('/settings/connections', headers=self.auth,
                         json={'kind': 'llm', 'provider': 'fake', 'model': 'fake-1', 'api_key': 'x'})

    def vote(self, pid, n=4, auth=None):
        return self.client.post(f'/positions/{pid}/vote', json={'interesse': n}, headers=auth or self.auth)

    def status(self, pid, **body):
        return self.client.post(f'/positions/{pid}/status', json=body, headers=self.auth)

    def test_normalize_url(self):
        self.assertEqual(normalize_url('https://Jobs.Example.com/a/?utm_source=x&id=3#top'),
                         'https://jobs.example.com/a?id=3')
        self.assertEqual(normalize_url('https://a.com/?z=1&b=2&gclid=q'), 'https://a.com/?b=2&z=1')

    def test_normalize_key(self):
        # "S.p.A." -> i punti si tolgono: "spa"
        self.assertEqual(normalize_key('ACME S.p.A.', 'Dev  Python'), normalize_key('acme spa', 'dev python'))
        self.assertEqual(normalize_key('Acme', 'Dev-Python'), 'acme|dev python')

    def test_normalize_url_malformed(self):
        self.assertEqual(normalize_url(' http://[Bad '), 'http://[bad')

    def test_find_duplicate(self):
        pid = self.make()  # https://x.it/a, Dev, Acme
        with self.app.app_context():
            self.assertEqual(find_duplicate(1, 'https://X.it/a/?utm_source=z', 'Altra', 'Altro').id, pid)
            self.assertEqual(find_duplicate(1, 'https://y.it/b', 'ACME', 'dev').id, pid)
            self.assertIsNone(find_duplicate(2, 'https://x.it/a', 'Acme', 'Dev'))
            self.assertIsNone(find_duplicate(1, 'https://y.it/b', 'Acme', 'Altro'))
            self.assertIsNone(find_duplicate(1, '', '', ''))
            self.assertIsNone(find_duplicate(1, '', 'Acme', ''))
            db.session.add(Position(user_id=1, azienda='', titolo=''))
            db.session.commit()
            self.assertIsNone(find_duplicate(1, '', '', ''))

    def test_classify_fallback(self):
        self.assertEqual(classify_reason('no', None), {'tipo': 'generico', 'preferenza': None})
        self.assertEqual(classify_reason('stipendio troppo basso qui', None)['tipo'], 'annuncio')

    def test_status_without_vote_409(self):
        pid = self.make()
        self.assertEqual(self.status(pid, stato='promossa').status_code, 409)

    def test_invalid_transition_400(self):
        pid = self.make()
        self.vote(pid)
        self.assertEqual(self.status(pid, stato='candidato').status_code, 400)

    def test_vote_validation(self):
        pid = self.make()
        for bad in (0, 6, True, '3', None):
            self.assertEqual(self.vote(pid, bad).status_code, 400)
        self.assertEqual(self.vote(pid, 3).status_code, 200)

    def test_bocciata_requires_motivo(self):
        pid = self.make()
        self.vote(pid)
        self.assertEqual(self.status(pid, stato='bocciata').status_code, 400)

    def test_generic_reason_422_then_confirm(self):
        pid = self.make()
        self.vote(pid)
        r = self.status(pid, stato='bocciata', motivo='no')
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.get_json()['code'], 'motivo_generico')
        with self.app.app_context():
            self.assertIsNone(db.session.get(Position, pid).motivo)
            self.assertEqual(PositionEvent.query.filter_by(position_id=pid).count(), 1)  # solo il voto
        self.assertEqual(self.client.get(f'/positions/{pid}', headers=self.auth).get_json()['stato'], 'da_valutare')
        r = self.status(pid, stato='bocciata', motivo='no', conferma_generico=True)
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual((d['stato'], d['motivo_tipo']), ('bocciata', 'generico'))

    def test_llm_preference(self):
        self.llm_on()
        FakeLlm.json_reply = {'tipo': 'preferenza', 'preferenza': 'evitare ruoli manageriali'}
        pid = self.make()
        self.vote(pid)
        d = self.status(pid, stato='bocciata', motivo='troppo manageriale').get_json()
        self.assertEqual(d['motivo_tipo'], 'preferenza')
        self.assertEqual(d['motivo_preferenza'], 'evitare ruoli manageriali')

    def test_llm_invalid_reply_falls_back(self):
        self.llm_on()
        FakeLlm.json_reply = {'tipo': 'boh'}
        pid = self.make()
        self.vote(pid)
        self.assertEqual(self.status(pid, stato='bocciata', motivo='no').status_code, 422)

    def test_promossa_with_motivo(self):
        pid = self.make()
        self.vote(pid)
        d = self.status(pid, stato='promossa', motivo='stack che mi interessa molto').get_json()
        self.assertEqual((d['stato'], d['motivo_tipo']), ('promossa', 'annuncio'))

    def test_events(self):
        pid = self.make()
        self.vote(pid, 3)
        self.vote(pid, 5)
        self.status(pid, stato='promossa', nota='ok')
        d = self.client.get(f'/positions/{pid}', headers=self.auth).get_json()
        ev = d['eventi']
        self.assertEqual(len(ev), 3)
        self.assertEqual((ev[0]['da_stato'], ev[0]['a_stato'], ev[0]['interesse']), ('da_valutare', 'da_valutare', 3))
        self.assertEqual((ev[2]['da_stato'], ev[2]['a_stato'], ev[2]['nota']), ('da_valutare', 'promossa', 'ok'))

    def test_other_user_404(self):
        pid = self.make()
        other = self.login('v')
        self.assertEqual(self.client.get(f'/positions/{pid}', headers=other).status_code, 404)
        self.assertEqual(self.vote(pid, auth=other).status_code, 404)
        self.assertEqual(self.client.post(f'/positions/{pid}/status', json={'stato': 'promossa'},
                                          headers=other).status_code, 404)
        self.assertEqual(self.client.delete(f'/positions/{pid}', headers=other).status_code, 404)
        self.assertEqual(self.client.get('/positions', headers=other).get_json(), [])

    def test_list_filters_and_delete(self):
        a, b = self.make(), self.make()
        self.vote(a)
        self.status(a, stato='promossa')
        r = self.client.get('/positions?stato=promossa', headers=self.auth).get_json()
        self.assertEqual([p['id'] for p in r], [a])
        r = self.client.get('/positions?origine=manuale', headers=self.auth).get_json()
        self.assertEqual([p['id'] for p in r], [b, a])  # più recenti prima
        self.assertEqual(self.client.delete(f'/positions/{a}', headers=self.auth).status_code, 200)
        with self.app.app_context():
            self.assertEqual(PositionEvent.query.filter_by(position_id=a).count(), 0)

    def test_delete_profile_detaches_positions(self):
        pr = self.client.post('/search-profiles', json={'name': 'p'}, headers=self.auth).get_json()['id']
        pid = self.make(profile_id=pr)
        self.assertEqual(self.client.delete(f'/search-profiles/{pr}', headers=self.auth).status_code, 200)
        self.assertIsNone(self.client.get(f'/positions/{pid}', headers=self.auth).get_json()['profile_id'])


if __name__ == '__main__':
    unittest.main()
