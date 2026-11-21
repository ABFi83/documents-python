import html
import re

import requests

from app.services.ai.base import AdapterError, SearchAdapter, SearchResult

URL = 'https://api.search.brave.com/res/v1/web/search'
MAX_COUNT = 20  # limite documentato dell'API per pagina


def _pulisci(s: str) -> str:
    # Brave evidenzia i termini con <strong> e usa entità HTML negli snippet
    return html.unescape(re.sub(r'<[^>]+>', '', s or ''))


class BraveSearch(SearchAdapter):
    provider = 'brave'

    def _get(self, query: str, n: int) -> dict:
        # Messaggi fissi: mai str(e) né la risposta, per non esporre la chiave.
        try:
            r = requests.get(URL, params={'q': query, 'count': max(1, min(n, MAX_COUNT))},
                             headers={'X-Subscription-Token': self.api_key, 'Accept': 'application/json'},
                             timeout=20)
        except requests.RequestException:
            raise AdapterError('Impossibile contattare Brave Search')
        if r.status_code in (401, 403):
            raise AdapterError('Chiave API Brave non valida')
        if r.status_code == 429:
            raise AdapterError('Limite di richieste Brave superato, riprova più tardi')
        if not r.ok:
            raise AdapterError(f'Errore Brave Search (HTTP {r.status_code})')
        try:
            return r.json()
        except ValueError:
            raise AdapterError('Risposta non valida da Brave Search')

    def search(self, query, n):
        risultati = (self._get(query, n).get('web') or {}).get('results') or []
        return [SearchResult(url=x.get('url', ''), title=_pulisci(x.get('title')),
                             snippet=_pulisci(x.get('description'))) for x in risultati]

    def test(self):
        self._get('test', 1)
