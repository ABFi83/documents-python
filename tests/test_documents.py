import io
import tempfile
import unittest
from unittest.mock import patch

from app import create_app, db
import os

from app.models import Document, Experience, Process, ProcessStatus, Skill, User
from app.services.extract_service import extract_info_from_text

CV_A = "Mario Rossi\nCOMPETENZE\nPython, Django\nESPERIENZA PROFESSIONALE\nDeveloper — Acme set 2020 – oggi\nBackend.\n"
CV_B = "Mario Rossi\nCOMPETENZE TECNICHE\nJava, Spring Boot\nESPERIENZE\nBeta Srl 01/2015 - 12/2019\nAnalista\n"


# stessa esperienza di CV_A (case diverso) + Python di nuovo
CV_C = "Mario Rossi\nCOMPETENZE\npython, React\nESPERIENZA PROFESSIONALE\ndeveloper — ACME set 2020 – oggi\nAltro testo.\n"
CVS = {'a.pdf': CV_A, 'b.pdf': CV_B, 'c.pdf': CV_C}


class DeferredThread:
    """Mette i thread in coda: il test decide quando farli girare (CV 'in analisi')."""
    queue = []

    def __init__(self, target, args):
        self.target, self.args = target, args

    def start(self):
        DeferredThread.queue.append(self)

    @classmethod
    def run_all(cls):
        while cls.queue:
            t = cls.queue.pop(0)
            t.target(*t.args)


class SyncThread:
    """Esegue il target subito, così il test vede l'estrazione finita."""
    def __init__(self, target, args):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class DocumentsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'UPLOAD_FOLDER': self.tmp.name})
        self.client = self.app.test_client()
        self.client.post('/auth/register', json={'username': 'u', 'password': 'p'})
        token = self.client.post('/auth/login', json={'username': 'u', 'password': 'p'}).get_json()['access_token']
        self.auth = {'Authorization': f'Bearer {token}'}

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.tmp.cleanup()

    def upload(self, *names, field='files'):
        data = {field: [(io.BytesIO(b'%PDF'), n) for n in names]}
        return self.client.post('/documents', data=data, headers=self.auth, content_type='multipart/form-data')

    @patch('app.routes.documents.Thread', SyncThread)
    @patch('app.routes.documents.pdf_to_text', side_effect=lambda url, name, data: CV_A if name == 'a.pdf' else CV_B)
    def test_upload_many_and_history(self, _pdf):
        r = self.upload('a.pdf', 'b.pdf')
        self.assertEqual(r.status_code, 202)
        self.assertEqual(len(r.get_json()), 2)

        history = self.client.get('/documents', headers=self.auth).get_json()
        self.assertEqual([d['title'] for d in history], ['b.pdf', 'a.pdf'])  # più recente prima
        by_title = {d['title']: d['process'] for d in history}
        self.assertEqual(by_title['a.pdf']['status'], 'COMPLETED')
        self.assertEqual(by_title['a.pdf']['result']['linguaggi'], ['Python'])
        self.assertEqual(by_title['a.pdf']['result']['esperienze'][0]['azienda'], 'Acme')
        self.assertEqual(by_title['a.pdf']['result']['esperienze'][0]['start_date'], '2020-09-01')
        self.assertEqual(sorted(by_title['b.pdf']['result']['frameworks']), ['Spring Boot'])
        self.assertIsNotNone(by_title['b.pdf']['end_date'])

        detail = self.client.get(f"/documents/{history[1]['id']}", headers=self.auth).get_json()
        self.assertEqual(detail['process']['result']['linguaggi'], ['Python'])

        with self.app.app_context():
            # skill/esperienze solo nello storico, non nel profilo; il nome sì
            self.assertEqual(Skill.query.count(), 0)
            self.assertEqual(Experience.query.count(), 0)
            self.assertEqual(db.session.get(User, 1).name, 'Mario')

    @patch('app.routes.documents.Thread', SyncThread)
    @patch('app.routes.documents.pdf_to_text', return_value=CV_A)
    def test_single_file_old_field_and_title(self, _pdf):
        r = self.client.post('/documents', headers=self.auth, content_type='multipart/form-data',
                             data={'file': (io.BytesIO(b'%PDF'), 'cv.pdf'), 'title': 'Il mio CV'})
        self.assertEqual(r.status_code, 202)
        self.assertEqual(self.client.get('/documents', headers=self.auth).get_json()[0]['title'], 'Il mio CV')

    def test_rejects_non_pdf_and_empty(self):
        r = self.upload('a.pdf', 'b.docx')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['files'], ['b.docx'])
        self.assertEqual(self.client.get('/documents', headers=self.auth).get_json(), [])
        self.assertEqual(self.client.post('/documents', headers=self.auth, data={}).status_code, 400)

    def test_other_user_cannot_see_document(self):
        self.assertEqual(self.client.get('/documents/1', headers=self.auth).status_code, 404)

    @patch('app.routes.documents.Thread', SyncThread)
    @patch('app.routes.documents.pdf_to_text', return_value=CV_A)
    def test_delete_document(self, _pdf):
        self.upload('a.pdf')
        doc = self.client.get('/documents', headers=self.auth).get_json()[0]
        self.assertTrue(os.path.exists(doc['file_path']))

        r = self.client.delete(f"/documents/{doc['id']}", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get('/documents', headers=self.auth).get_json(), [])
        self.assertEqual(self.client.get(f"/documents/{doc['id']}", headers=self.auth).status_code, 404)
        self.assertFalse(os.path.exists(doc['file_path']))
        with self.app.app_context():
            self.assertEqual(Process.query.count(), 0)
        self.assertEqual(self.client.delete(f"/documents/{doc['id']}", headers=self.auth).status_code, 404)

    @patch('app.routes.documents.Thread', DeferredThread)
    @patch('app.routes.documents.pdf_to_text', return_value=CV_A)
    def test_delete_while_analyzing_writes_nothing(self, pdf):
        DeferredThread.queue = []
        self.upload('a.pdf', 'b.pdf')
        history = self.client.get('/documents', headers=self.auth).get_json()
        self.assertEqual({d['process']['status'] for d in history}, {'PENDING'})
        for d in history:
            self.client.delete(f"/documents/{d['id']}", headers=self.auth)

        DeferredThread.run_all()  # i thread partono dopo la cancellazione

        pdf.assert_not_called()  # niente Docling per CV già cancellati
        with self.app.app_context():
            self.assertEqual(Process.query.count(), 0)
            self.assertIsNone(db.session.get(User, 1).name)

    def test_extraction_finishing_after_delete_writes_nothing(self):
        """Cancellazione mentre Docling lavora: il salvataggio trova il processo sparito."""
        with self.app.app_context():
            doc = Document(user_id=1, title='a.pdf', file_path='x')
            process = Process(user_id=1, status=ProcessStatus.PENDING, document=doc)
            db.session.add_all([doc, process])
            db.session.commit()
            pid = process.id
            db.session.delete(process)
            db.session.delete(doc)
            db.session.commit()

            self.assertIsNone(extract_info_from_text(pid, CV_A))
            user = db.session.get(User, 1)
            self.assertIsNone(user.name)
            self.assertIsNone(user.surname)
            self.assertEqual(Process.query.count(), 0)

    @patch('app.routes.documents.Thread', SyncThread)
    @patch('app.routes.documents.pdf_to_text', side_effect=lambda url, name, data: CVS[name])
    def test_summary(self, _pdf):
        self.upload('a.pdf', 'b.pdf', 'c.pdf')
        ids = {d['title']: d['id'] for d in self.client.get('/documents', headers=self.auth).get_json()}
        with self.app.app_context():  # un CV ancora in analisi non entra nella somma
            pending = Document(user_id=1, title='p.pdf', file_path='x')
            db.session.add_all([pending, Process(user_id=1, status=ProcessStatus.PENDING, document=pending)])
            db.session.commit()

        s = self.client.get('/documents/summary', headers=self.auth).get_json()
        self.assertEqual(s['documenti'], 3)
        self.assertEqual(s['linguaggi'][0], {'nome': 'Python', 'document_ids': [ids['c.pdf'], ids['a.pdf']]})
        self.assertEqual({l['nome'] for l in s['linguaggi']}, {'Python', 'Java'})
        self.assertEqual({f['nome'] for f in s['frameworks']}, {'Django', 'Spring Boot', 'React'})
        self.assertEqual([(e['azienda'], e['start_date'], e['document_ids']) for e in s['esperienze']], [
            ('ACME', '2020-09-01', [ids['c.pdf'], ids['a.pdf']]),  # dedup, dati del CV più recente
            ('Beta Srl', '2015-01-01', [ids['b.pdf']]),
        ])

    def test_summary_empty(self):
        s = self.client.get('/documents/summary', headers=self.auth).get_json()
        self.assertEqual(s, {'documenti': 0, 'linguaggi': [], 'frameworks': [], 'esperienze': []})


if __name__ == '__main__':
    unittest.main()
