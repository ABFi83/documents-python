import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

from app import create_app, db
from app.models import Position, SearchRun, RunStatus
from app.services.ai.base import SearchResult
from tests.fakes import FakeLlm, FakeSearch, register_fakes, reset_fakes
from tests.test_documents import SyncThread

URL = 'https://jobs.example.it/annuncio/42'


def salva(url=URL, titolo='Backend Developer', azienda='Acme', **kw):
    d = {'url': url, 'titolo': titolo, 'azienda': azienda, 'punteggio': 80, 'motivazione': 'adatta',
         'skill_presenti': ['Python'], 'skill_mancanti': []}
    d.update(kw)
    return ('salva_posizione', d)


CERCA = ('cerca_web', {'query': 'backend developer', 'max_risultati': 5})


class AgentRunnerTestCase(unittest.TestCase):
    def setUp(self):
        register_fakes()
        reset_fakes()
        FakeSearch.results = [SearchResult(url=URL, title='Backend Developer - Acme', snippet='...')]
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'ENCRYPTION_KEY': Fernet.generate_key().decode()})
        for target in ('app.routes.search_profiles.Thread', 'app.routes.runs.Thread'):
            p = patch(target, SyncThread)
            p.start()
            self.addCleanup(p.stop)
        self.client = self.app.test_client()
        self.client.post('/auth/register', json={'username': 'u', 'password': 'p'})
        token = self.client.post('/auth/login', json={'username': 'u', 'password': 'p'}).get_json()['access_token']
        self.auth = {'Authorization': f'Bearer {token}'}
        self.llm_id = self.conn('llm')
        self.search_id = self.conn('search')
        self.profile_id = self.client.post('/search-profiles', headers=self.auth, json={
            'name': 'Backend', 'criteria': {'ruoli': ['Backend Developer'], 'luogo': 'Milano'}}).get_json()['id']

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def conn(self, kind):
        body = {'kind': kind, 'provider': 'fake', 'api_key': 'sk-segreta'}
        return self.client.post('/settings/connections', headers=self.auth, json=body).get_json()['id']

    def start(self):
        return self.client.post(f'/search-profiles/{self.profile_id}/runs', headers=self.auth)

    def run_json(self, run_id):
        return self.client.get(f'/runs/{run_id}', headers=self.auth).get_json()

    def positions(self):
        with self.app.app_context():
            return Position.query.all()

    def last_results(self, i=-1):
        """tool_results dell'ultimo messaggio utente visto dall'LLM nello step i."""
        return FakeLlm.received[i][-1]['tool_results']

    def add_position(self, **kw):
        with self.app.app_context():
            db.session.add(Position(user_id=1, origine='manuale', **kw))
            db.session.commit()

    def test_run_completo(self):
        FakeLlm.script = [{'tool_calls': [CERCA]}, {'tool_calls': [salva(url=URL + '?utm_source=x')]}]
        r = self.start()
        self.assertEqual(r.status_code, 202)
        run = self.run_json(r.get_json()['id'])
        self.assertEqual(run['status'], 'COMPLETED')
        self.assertEqual(run['counters']['salvate'], 1)
        self.assertEqual(run['counters']['ricerche'], 1)
        self.assertEqual(len(run['positions']), 1)
        p = self.positions()[0]
        self.assertEqual((p.origine, p.run_id, p.profile_id, p.punteggio_ai), ('agente', run['id'], self.profile_id, 80))
        self.assertFalse(self.last_results()[0]['is_error'])
        self.assertIsNotNone(run['end_date'])

    def test_link_non_verificato(self):
        FakeLlm.script = [{'tool_calls': [salva(url='https://inventato.it/x')]}]
        run = self.run_json(self.start().get_json()['id'])
        self.assertEqual(self.positions(), [])
        self.assertEqual(run['counters']['scartate']['link_non_verificato'], 1)
        self.assertTrue(self.last_results()[0]['is_error'])

    def test_doppione_e_gia_valutata(self):
        self.add_position(url='https://altro.it/1', titolo='backend developer', azienda='ACME')
        self.add_position(url=URL + '/b', titolo='Data Engineer', azienda='Beta', interesse=4)
        FakeSearch.results = [SearchResult(url=URL, title='t', snippet='s'),
                              SearchResult(url=URL + '/b', title='t', snippet='s')]
        FakeLlm.script = [{'tool_calls': [CERCA]},
                          {'tool_calls': [salva(), salva(url=URL + '/b', titolo='Altro', azienda='Gamma')]}]
        run = self.run_json(self.start().get_json()['id'])
        self.assertEqual(len(self.positions()), 2)
        self.assertEqual(run['counters']['scartate']['doppione'], 1)
        self.assertEqual(run['counters']['scartate']['gia_valutata'], 1)
        self.assertEqual(run['counters']['salvate'], 0)
        self.assertTrue(all(r['is_error'] for r in self.last_results()))

    def test_doppione_nello_stesso_turno(self):
        FakeLlm.script = [{'tool_calls': [CERCA]}, {'tool_calls': [salva(), salva(url=URL + '?ref=a')]}]
        run = self.run_json(self.start().get_json()['id'])
        self.assertEqual(len(self.positions()), 1)
        self.assertEqual(run['counters']['scartate']['doppione'], 1)

    def test_domanda_e_risposta(self):
        FakeLlm.script = [{'tool_calls': [CERCA, ('fai_domanda', {'domanda': 'Anche Torino?'})]}]
        run = self.start().get_json()
        run = self.run_json(run['id'])
        self.assertEqual(run['status'], 'WAITING_INPUT')
        self.assertEqual(run['question'], 'Anche Torino?')
        self.assertEqual(len(FakeLlm.received), 1)

        r = self.client.post(f"/runs/{run['id']}/answer", headers=self.auth, json={'testo': 'Sì'})
        self.assertEqual(r.status_code, 202)
        self.assertEqual(len(FakeLlm.received), 2)
        risultati = self.last_results()
        self.assertEqual(len(risultati), 2)
        self.assertIn(URL, risultati[0]['content'])
        self.assertEqual(risultati[1]['content'], 'Sì')
        self.assertEqual(FakeLlm.received[1][-2]['role'], 'assistant')  # nessun messaggio in mezzo
        run = self.run_json(run['id'])
        self.assertEqual(run['status'], 'COMPLETED')
        self.assertIsNone(run['question'])
        # la domanda con risposta già data -> 409
        r = self.client.post(f"/runs/{run['id']}/answer", headers=self.auth, json={'testo': 'Sì'})
        self.assertEqual(r.status_code, 409)

    def test_cancel_in_attesa_poi_answer(self):
        FakeLlm.script = [{'tool_calls': [('fai_domanda', {'domanda': '?'})]}]
        run_id = self.start().get_json()['id']
        self.assertEqual(self.client.post(f'/runs/{run_id}/cancel', headers=self.auth).status_code, 200)
        self.assertEqual(self.run_json(run_id)['status'], 'CANCELLED')
        r = self.client.post(f'/runs/{run_id}/answer', headers=self.auth, json={'testo': 'x'})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.client.post(f'/runs/{run_id}/cancel', headers=self.auth).status_code, 409)

    def test_cancel_durante_il_passo(self):
        test = self
        orig = FakeSearch.search

        def search_e_annulla(self_, query, n):
            test.client.post('/runs/1/cancel', headers=test.auth)
            return orig(self_, query, n)

        FakeLlm.script = [{'tool_calls': [CERCA, salva()]}, {'tool_calls': [CERCA]}]
        with patch.object(FakeSearch, 'search', search_e_annulla):
            self.start()
        self.assertEqual(self.positions(), [])
        run = self.run_json(1)
        self.assertEqual(run['status'], 'CANCELLED')
        self.assertEqual(run['counters']['ricerche'], 0)  # nulla scritto da quel passo
        self.assertEqual(len(FakeLlm.received), 1)

    def test_errore_ricerca_non_ferma_il_run(self):
        FakeSearch.error = 'Ricerca non disponibile'
        FakeLlm.script = [{'tool_calls': [CERCA]}]
        run = self.run_json(self.start().get_json()['id'])
        res = self.last_results()[0]
        self.assertTrue(res['is_error'])
        self.assertIn('Ricerca non disponibile', res['content'])
        self.assertEqual(run['status'], 'COMPLETED')

    def test_errore_llm(self):
        FakeLlm.script = [{'error': 'Chiave non valida'}]
        run = self.run_json(self.start().get_json()['id'])
        self.assertEqual(run['status'], 'ERROR')
        self.assertEqual(run['error_message'], 'Chiave non valida')

    def test_eccezione_inattesa(self):
        FakeLlm.script = [{'tool_calls': [CERCA]}]
        with patch('app.services.agent.tools.normalize_url', side_effect=RuntimeError('sk-segreta')):
            run = self.run_json(self.start().get_json()['id'])
        self.assertEqual(run['status'], 'ERROR')
        self.assertNotIn('sk-segreta', run['error_message'])

    def test_secondo_avvio_409(self):
        FakeLlm.script = [{'tool_calls': [('fai_domanda', {'domanda': '?'})]}]
        self.assertEqual(self.start().status_code, 202)
        self.assertEqual(self.start().status_code, 409)

    def test_avvio_senza_search_400(self):
        self.client.patch(f'/settings/connections/{self.search_id}', headers=self.auth, json={'active': False})
        r = self.start()
        self.assertEqual(r.status_code, 400)
        with self.app.app_context():
            self.assertEqual(SearchRun.query.count(), 0)

    def test_utente_senza_cv(self):
        self.start()
        self.assertIn('Backend Developer', FakeLlm.received[0][0]['content'])
        self.assertIn('Milano', FakeLlm.received[0][0]['content'])

    def test_limite_passi(self):
        self.app.config['AGENT_MAX_STEPS'] = 3
        FakeLlm.script = [{'tool_calls': [CERCA]} for _ in range(10)]
        run = self.run_json(self.start().get_json()['id'])
        self.assertEqual(run['status'], 'COMPLETED')
        self.assertEqual(run['steps'], 3)
        self.assertEqual(len(FakeLlm.received), 3)

    def test_limite_ricerche(self):
        self.app.config['AGENT_MAX_SEARCHES'] = 1
        FakeLlm.script = [{'tool_calls': [CERCA, CERCA]}]
        run = self.run_json(self.start().get_json()['id'])
        self.assertEqual(run['counters']['ricerche'], 1)
        self.assertTrue(self.last_results()[1]['is_error'])
        self.assertIn('limite ricerche raggiunto', self.last_results()[1]['content'])

    def test_leggi_pagina_verifica_url(self):
        url = 'https://altro.it/annuncio'
        FakeLlm.script = [{'tool_calls': [('leggi_pagina', {'url': url})]}, {'tool_calls': [salva(url=url)]}]
        with patch('app.services.agent.tools.read_page', return_value='testo annuncio') as rp:
            run = self.run_json(self.start().get_json()['id'])
        rp.assert_called_once()
        self.assertEqual(run['counters']['pagine_lette'], 1)
        self.assertEqual(run['counters']['salvate'], 1)

    def test_lista_delete_run_e_connessione_in_uso(self):
        FakeLlm.script = [{'tool_calls': [CERCA, ('fai_domanda', {'domanda': '?'})]}]
        run_id = self.start().get_json()['id']
        runs = self.client.get(f'/search-profiles/{self.profile_id}/runs', headers=self.auth).get_json()
        self.assertEqual([r['id'] for r in runs], [run_id])
        self.assertEqual(self.client.delete(f'/settings/connections/{self.llm_id}', headers=self.auth).status_code, 409)
        self.add_position(url='https://x.it', titolo='a', azienda='b', run_id=run_id)
        self.assertEqual(self.client.delete(f'/runs/{run_id}', headers=self.auth).status_code, 200)
        self.assertIsNone(self.positions()[0].run_id)
        self.assertEqual(self.client.get(f'/runs/{run_id}', headers=self.auth).status_code, 404)
        self.assertEqual(self.client.delete(f'/settings/connections/{self.llm_id}', headers=self.auth).status_code, 200)

    def test_delete_profilo_annulla_run(self):
        FakeLlm.script = [{'tool_calls': [('fai_domanda', {'domanda': '?'})]}]
        run_id = self.start().get_json()['id']
        self.client.delete(f'/search-profiles/{self.profile_id}', headers=self.auth)
        with self.app.app_context():
            run = db.session.get(SearchRun, run_id)
            self.assertEqual((run.status, run.profile_id), (RunStatus.CANCELLED, None))

    def test_run_altrui_404(self):
        FakeLlm.script = [{'tool_calls': [('fai_domanda', {'domanda': '?'})]}]
        run_id = self.start().get_json()['id']
        self.client.post('/auth/register', json={'username': 'v', 'password': 'p'})
        tok = self.client.post('/auth/login', json={'username': 'v', 'password': 'p'}).get_json()['access_token']
        other = {'Authorization': f'Bearer {tok}'}
        self.assertEqual(self.client.get(f'/runs/{run_id}', headers=other).status_code, 404)
        self.assertEqual(self.client.post(f'/runs/{run_id}/cancel', headers=other).status_code, 404)


if __name__ == '__main__':
    unittest.main()
