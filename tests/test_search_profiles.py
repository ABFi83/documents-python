import io
import tempfile
import unittest
from unittest.mock import patch

from app import create_app, db
from app.models import Document, Process, ProcessStatus
from tests.test_documents import SyncThread

CV_A = ("Mario Rossi\nBackend Developer · Python\nCOMPETENZE\nPython, Django\nESPERIENZA PROFESSIONALE\n"
        "Developer — Acme set 2020 – oggi\nBackend.\n")
CV_B = ("Mario Rossi\nbackend developer\nCOMPETENZE TECNICHE\nJava, Spring Boot\nESPERIENZE\n"
        "Beta Srl 01/2015 - 12/2019\nAnalista\n")


class SearchProfilesTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'UPLOAD_FOLDER': self.tmp.name})
        self.client = self.app.test_client()
        self.auth = self.register('u')
        self.other = self.register('v')

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.tmp.cleanup()

    def register(self, name):
        self.client.post('/auth/register', json={'username': name, 'password': 'p'})
        token = self.client.post('/auth/login', json={'username': name, 'password': 'p'}).get_json()['access_token']
        return {'Authorization': f'Bearer {token}'}

    def test_crud_with_defaults(self):
        r = self.client.post('/search-profiles', headers=self.auth, json={
            'name': 'Backend', 'criteria': {'ruoli': ['Dev'], 'modalita': ['remoto'],
                                            'competenze': [{'nome': 'Python', 'obbligatoria': True}]}})
        self.assertEqual(r.status_code, 201)
        p = r.get_json()
        self.assertEqual(p['criteria']['max_giorni_annuncio'], 30)
        self.assertEqual(p['criteria']['lingue'], [])
        self.assertIsNone(p['criteria']['ral_min'])

        self.assertEqual(self.client.get('/search-profiles', headers=self.auth).get_json()[0]['name'], 'Backend')
        self.assertEqual(self.client.get(f"/search-profiles/{p['id']}", headers=self.auth).get_json()['name'], 'Backend')

        r = self.client.put(f"/search-profiles/{p['id']}", headers=self.auth,
                            json={'name': 'Nuovo', 'criteria': {'ral_min': 40000}})
        self.assertEqual(r.get_json()['name'], 'Nuovo')
        self.assertEqual(r.get_json()['criteria']['ral_min'], 40000)
        self.assertEqual(r.get_json()['criteria']['ruoli'], [])  # sostituzione completa

        self.assertEqual(self.client.delete(f"/search-profiles/{p['id']}", headers=self.auth).status_code, 200)
        self.assertEqual(self.client.get('/search-profiles', headers=self.auth).get_json(), [])

    def test_name_only_gets_default_criteria(self):
        r = self.client.post('/search-profiles', headers=self.auth, json={'name': 'X'})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()['criteria']['max_giorni_annuncio'], 30)

    def test_validation_errors(self):
        post = lambda body: self.client.post('/search-profiles', headers=self.auth, json=body)
        self.assertEqual(post({'name': 'X', 'criteria': {'modalita': ['spazio']}}).status_code, 400)
        self.assertEqual(post({'criteria': {}}).status_code, 400)
        self.assertEqual(post({'name': 'X', 'criteria': {'boh': 1}}).status_code, 400)
        r = post({'name': 'X', 'criteria': {'ral_min': 'tanto'}})
        self.assertEqual(r.status_code, 400)
        self.assertIn('ral_min', r.get_json()['errors']['criteria'])

    def test_other_user_gets_404(self):
        pid = self.client.post('/search-profiles', headers=self.auth, json={'name': 'X'}).get_json()['id']
        url = f'/search-profiles/{pid}'
        self.assertEqual(self.client.get(url, headers=self.other).status_code, 404)
        self.assertEqual(self.client.put(url, headers=self.other, json={'name': 'Y'}).status_code, 404)
        self.assertEqual(self.client.delete(url, headers=self.other).status_code, 404)
        self.assertEqual(self.client.get('/search-profiles', headers=self.other).get_json(), [])
        self.assertEqual(self.client.get(url, headers=self.auth).status_code, 200)

    def test_suggestions_empty_without_cv(self):
        r = self.client.get('/search-profiles/suggestions', headers=self.auth)
        self.assertEqual(r.get_json(), {'ruoli': [], 'competenze': []})

    @patch('app.routes.documents.Thread', SyncThread)
    @patch('app.routes.documents.pdf_to_text', side_effect=lambda url, name, data: CV_A if name == 'a.pdf' else CV_B)
    def test_suggestions_from_cvs(self, _pdf):
        for n in ('a.pdf', 'b.pdf'):
            data = {'files': [(io.BytesIO(b'%PDF'), n)]}
            self.client.post('/documents', data=data, headers=self.auth, content_type='multipart/form-data')
        s = self.client.get('/search-profiles/suggestions', headers=self.auth).get_json()
        # ruolo obiettivo del CV più recente (B) per primo; "Backend Developer" di A non raddoppia
        self.assertEqual(s['ruoli'][0], 'backend developer')
        self.assertEqual(sum(r.casefold() == 'backend developer' for r in s['ruoli']), 1)
        self.assertIn('Developer', s['ruoli'])  # ruolo di un'esperienza
        self.assertEqual(sorted(s['competenze']), ['Django', 'Java', 'Python', 'Spring Boot'])
        # altro utente: niente
        self.assertEqual(self.client.get('/search-profiles/suggestions', headers=self.other).get_json(),
                         {'ruoli': [], 'competenze': []})

    def test_suggestions_senza_nome(self):
        # CV estratto prima del fix: il "ruolo obiettivo" era il nome
        with self.app.app_context():
            d = Document(user_id=1, title='cv')
            db.session.add(d)
            db.session.flush()
            db.session.add(Process(user_id=1, document_id=d.id, status=ProcessStatus.COMPLETED, result={
                'nome': 'Mario', 'cognome': 'Rossi', 'ruolo_obiettivo': 'Mario Rossi',
                'esperienze': [{'azienda': 'Acme', 'ruolo': 'Developer', 'start_date': None}]}))
            db.session.commit()
        s = self.client.get('/search-profiles/suggestions', headers=self.auth).get_json()
        self.assertEqual(s['ruoli'], ['Developer'])


if __name__ == '__main__':
    unittest.main()
