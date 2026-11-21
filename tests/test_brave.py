import unittest
from unittest.mock import patch, MagicMock

import requests

from app.services.ai.base import AdapterError, SearchResult
from app.services.ai.brave import BraveSearch
from app.services.ai.registry import SEARCH_PROVIDERS

CHIAVE = 'BSA-segretissima'


def risposta(status=200, data=None):
    r = MagicMock(status_code=status, ok=status < 400)
    r.json.return_value = data
    return r


class BraveSearchTestCase(unittest.TestCase):
    def setUp(self):
        p = patch('app.services.ai.brave.requests.get')
        self.get = p.start()
        self.addCleanup(p.stop)
        self.s = BraveSearch(CHIAVE)

    def test_registrato(self):
        self.assertIs(SEARCH_PROVIDERS['brave']['cls'], BraveSearch)

    def test_search_mappa_risultati(self):
        self.get.return_value = risposta(data={'web': {'results': [
            {'url': 'https://a.it/1', 'title': 'Dev Python', 'description': 'Cerchiamo <strong>Python</strong> dev &amp; co'},
            {'url': 'https://b.it/2', 'title': 'Altro'},
        ]}})
        out = self.s.search('sviluppatore python milano', 5)
        self.assertEqual(out, [SearchResult('https://a.it/1', 'Dev Python', 'Cerchiamo Python dev & co'),
                               SearchResult('https://b.it/2', 'Altro', '')])
        args, kw = self.get.call_args
        self.assertEqual(args[0], 'https://api.search.brave.com/res/v1/web/search')
        self.assertEqual(kw['params'], {'q': 'sviluppatore python milano', 'count': 5})
        self.assertEqual(kw['headers'], {'X-Subscription-Token': CHIAVE, 'Accept': 'application/json'})
        self.assertEqual(kw['timeout'], 20)

    def test_count_limitato_e_nessun_risultato(self):
        self.get.return_value = risposta(data={'query': {}})
        self.assertEqual(self.s.search('x', 50), [])
        self.assertEqual(self.get.call_args.kwargs['params']['count'], 20)

    def test_http_401(self):
        self.get.return_value = risposta(401)
        with self.assertRaises(AdapterError) as cm:
            self.s.search('x', 5)
        self.assertNotIn(CHIAVE, str(cm.exception))

    def test_errori_vari_senza_chiave(self):
        for effetto in (risposta(429), risposta(500), requests.ConnectionError(f'giu {CHIAVE}')):
            self.get.side_effect = None
            if isinstance(effetto, Exception):
                self.get.side_effect = effetto
            else:
                self.get.return_value = effetto
            with self.assertRaises(AdapterError) as cm:
                self.s.test()
            self.assertNotIn(CHIAVE, str(cm.exception))

    def test_test_ok(self):
        self.get.return_value = risposta(data={'web': {'results': []}})
        self.s.test()
        self.assertEqual(self.get.call_count, 1)


if __name__ == '__main__':
    unittest.main()
