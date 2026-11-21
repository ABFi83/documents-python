import unittest
from types import SimpleNamespace
from cryptography.fernet import Fernet
from app import create_app
from app.utils.crypto import encrypt
from app.services.ai.base import AdapterError, StepResult, ToolCall
from app.services.ai.registry import providers_info, llm_for, search_for
from tests.fakes import FakeLlm, FakeSearch, register_fakes, reset_fakes


def make_app(**extra):
    cfg = {'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
           'ENCRYPTION_KEY': Fernet.generate_key().decode()}
    cfg.update(extra)
    return create_app(cfg)


class RegistryTestCase(unittest.TestCase):
    def setUp(self):
        register_fakes()
        reset_fakes()
        self.app = make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def conn(self, provider='fake', key='sk-segreta'):
        return SimpleNamespace(provider=provider, model='m1', api_key_enc=encrypt(key))

    def test_providers_info(self):
        info = providers_info()
        self.assertIn('fake', [p['provider'] for p in info['llm']])
        self.assertIn('fake', [p['provider'] for p in info['search']])
        self.assertEqual(set(info['llm'][0]), {'provider', 'models', 'default_model'})

    def test_register_idempotente(self):
        register_fakes()
        self.assertEqual([p['provider'] for p in providers_info()['llm']].count('fake'), 1)

    def test_llm_for_chiave_decifrata(self):
        llm = llm_for(self.conn())
        self.assertIsInstance(llm, FakeLlm)
        self.assertEqual((llm.api_key, llm.model), ('sk-segreta', 'm1'))

    def test_search_for_chiave_decifrata(self):
        s = search_for(self.conn())
        self.assertIsInstance(s, FakeSearch)
        self.assertEqual(s.api_key, 'sk-segreta')

    def test_provider_sconosciuto(self):
        with self.assertRaises(AdapterError):
            llm_for(self.conn('boh'))
        with self.assertRaises(AdapterError):
            search_for(self.conn('boh'))

    def test_chiave_non_decifrabile(self):
        c = self.conn()
        c.api_key_enc = encrypt('x')[:-4] + 'AAAA'
        with self.assertRaises(AdapterError) as cm:
            llm_for(c)
        self.assertNotIn('sk-segreta', str(cm.exception))
        c.api_key_enc = Fernet(Fernet.generate_key()).encrypt(b'x').decode()
        with self.assertRaises(AdapterError):
            search_for(c)

    def test_encryption_key_assente(self):
        c = self.conn()
        self.app.config['ENCRYPTION_KEY'] = None
        with self.assertRaises(AdapterError):
            llm_for(c)

    def test_encryption_key_malformata(self):
        c = self.conn()
        self.app.config['ENCRYPTION_KEY'] = 'non-una-chiave'
        with self.assertRaises(AdapterError):
            search_for(c)


class FakeLlmTestCase(unittest.TestCase):
    def setUp(self):
        reset_fakes()

    def test_script_e_received(self):
        FakeLlm.script = [
            {'text': 'cerco', 'tool_calls': [('cerca_web', {'q': 'x'}), ('fai_domanda', {'d': 'y'})]},
        ]
        llm = FakeLlm('k', 'm')
        conv = llm.start('ciao')
        r = llm.step(conv, 'sys', [])
        self.assertIsInstance(r, StepResult)
        self.assertEqual([c.name for c in r.tool_calls], ['cerca_web', 'fai_domanda'])
        self.assertEqual(len({c.id for c in r.tool_calls}), 2)
        conv = llm.add_tool_results(r.conversation, [(r.tool_calls[0], 'ok', False), (r.tool_calls[1], 'si', False)])
        self.assertEqual(len(conv), 3)  # utente, assistente, un solo messaggio di risultati
        import json
        json.dumps(conv)
        # esaurito: nessuna chiamata
        r2 = llm.step(conv, 'sys', [])
        self.assertEqual(r2.tool_calls, [])
        self.assertEqual(len(FakeLlm.received), 2)

    def test_errore_e_json(self):
        FakeLlm.script = [{'error': 'giu'}]
        with self.assertRaises(AdapterError):
            FakeLlm('k', 'm').step([], 's', [])
        FakeLlm.json_reply = {'a': 1}
        self.assertEqual(FakeLlm('k', 'm').extract_json('p', {}), {'a': 1})

    def test_fake_search(self):
        from app.services.ai.base import SearchResult
        FakeSearch.results = [SearchResult('u', 't', 's')]
        self.assertEqual(len(FakeSearch('k').search('q', 5)), 1)
        FakeSearch.error = 'ko'
        with self.assertRaises(AdapterError):
            FakeSearch('k').search('q', 5)
