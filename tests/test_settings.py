import unittest

from cryptography.fernet import Fernet

from app import create_app, db
from app.models import AiConnection
from app.services.ai.registry import active_connection
from tests.fakes import register_fakes, reset_fakes


class SettingsTestCase(unittest.TestCase):
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

    def create(self, auth=None, **kw):
        body = {'kind': 'llm', 'provider': 'fake', 'api_key': 'sk-abcdef'}
        body.update(kw)
        return self.client.post('/settings/connections', json=body, headers=auth or self.auth)

    def test_providers(self):
        r = self.client.get('/settings/providers', headers=self.auth).get_json()
        self.assertIn('fake', [p['provider'] for p in r['llm']])
        self.assertIn('fake', [p['provider'] for p in r['search']])

    def test_create_hides_key_and_encrypts(self):
        r = self.create()
        self.assertEqual(r.status_code, 201)
        d = r.get_json()
        self.assertNotIn('api_key', d)
        self.assertNotIn('api_key_enc', d)
        self.assertEqual(d['key_last4'], 'cdef')
        self.assertEqual(d['model'], 'fake-1')  # default_model
        self.assertTrue(d['active'])  # la prima diventa attiva
        with self.app.app_context():
            self.assertNotEqual(db.session.get(AiConnection, d['id']).api_key_enc, 'sk-abcdef')
        lst = self.client.get('/settings/connections', headers=self.auth).get_json()
        self.assertEqual(len(lst), 1)
        self.assertNotIn('api_key_enc', lst[0])

    def test_second_active_deactivates_first(self):
        a = self.create().get_json()
        b = self.create(active=True, model='fake-2').get_json()
        self.assertTrue(b['active'])
        lst = {c['id']: c for c in self.client.get('/settings/connections', headers=self.auth).get_json()}
        self.assertFalse(lst[a['id']]['active'])
        with self.app.app_context():
            self.assertEqual(active_connection(1, 'llm').id, b['id'])
            self.assertIsNone(active_connection(1, 'search'))

    def test_second_not_active_by_default(self):
        self.create()
        self.assertFalse(self.create().get_json()['active'])

    def test_validation(self):
        self.assertEqual(self.create(provider='nope').status_code, 400)
        self.assertEqual(self.create(kind='boh').status_code, 400)
        self.assertEqual(self.create(api_key='').status_code, 400)
        self.assertEqual(self.create(model='non-esiste').status_code, 400)
        self.assertEqual(self.create(kind='search', provider='fake').status_code, 201)

    def test_no_encryption_key(self):
        self.app.config['ENCRYPTION_KEY'] = None
        r = self.create()
        self.assertEqual(r.status_code, 400)
        self.assertIn('ENCRYPTION_KEY', r.get_json()['msg'])

    def test_other_user_404(self):
        cid = self.create().get_json()['id']
        other = self.login('v')
        self.assertEqual(self.client.patch(f'/settings/connections/{cid}', json={'active': True}, headers=other).status_code, 404)
        self.assertEqual(self.client.delete(f'/settings/connections/{cid}', headers=other).status_code, 404)
        self.assertEqual(self.client.post(f'/settings/connections/{cid}/test', headers=other).status_code, 404)
        self.assertEqual(self.client.get('/settings/connections', headers=other).get_json(), [])

    def test_patch(self):
        a = self.create().get_json()
        b = self.create().get_json()
        r = self.client.patch(f'/settings/connections/{b["id"]}', json={'active': True, 'api_key': 'sk-zzzz1234', 'model': 'fake-2'},
                              headers=self.auth).get_json()
        self.assertEqual((r['active'], r['key_last4'], r['model']), (True, '1234', 'fake-2'))
        self.assertNotIn('api_key_enc', r)
        lst = {c['id']: c for c in self.client.get('/settings/connections', headers=self.auth).get_json()}
        self.assertFalse(lst[a['id']]['active'])

    def test_delete(self):
        cid = self.create().get_json()['id']
        self.assertEqual(self.client.delete(f'/settings/connections/{cid}', headers=self.auth).status_code, 200)
        self.assertEqual(self.client.get('/settings/connections', headers=self.auth).get_json(), [])

    def test_test_endpoint(self):
        cid = self.create().get_json()['id']
        r = self.client.post(f'/settings/connections/{cid}/test', headers=self.auth)
        self.assertEqual((r.status_code, r.get_json()), (200, {'ok': True}))
        from tests.fakes import FakeLlm
        FakeLlm.test_error = 'Chiave non valida'
        r = self.client.post(f'/settings/connections/{cid}/test', headers=self.auth)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json(), {'ok': False, 'msg': 'Chiave non valida'})

    def test_key_not_logged(self):
        with self.assertLogs(level='DEBUG') as cm:
            self.create()
        self.assertTrue(cm.output)
        self.assertFalse([l for l in cm.output if 'sk-abcdef' in l])
