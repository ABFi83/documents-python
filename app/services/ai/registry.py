from cryptography.fernet import InvalidToken

from app.services.ai.base import AdapterError
from app.services.ai.brave import BraveSearch
from app.services.ai.claude import ClaudeAdapter
from app.utils.crypto import decrypt, CryptoNotConfigured

# I test aggiungono "fake" (tests/fakes.py).
LLM_PROVIDERS: dict[str, dict] = {
    'claude': {'cls': ClaudeAdapter, 'models': ['claude-opus-5-5', 'claude-sonnet-5-5'],
               'default_model': 'claude-opus-5-5'},
}
SEARCH_PROVIDERS: dict[str, dict] = {'brave': {'cls': BraveSearch}}


def providers_info() -> dict:
    return {
        'llm': [{'provider': p, 'models': v['models'], 'default_model': v['default_model']}
                for p, v in LLM_PROVIDERS.items()],
        'search': [{'provider': p} for p in SEARCH_PROVIDERS],
    }


def _chiave(conn) -> str:
    try:
        return decrypt(conn.api_key_enc)
    except CryptoNotConfigured:
        raise AdapterError('Cifratura non configurata sul server')
    except (InvalidToken, ValueError):
        # ValueError: ENCRYPTION_KEY malformata. Mai includere la chiave nel messaggio.
        raise AdapterError('Chiave API non decifrabile: reinseriscila nelle impostazioni')


def _cls(registry: dict, provider: str):
    if provider not in registry:
        raise AdapterError(f'Provider non supportato: {provider}')
    return registry[provider]['cls']


def llm_for(conn):
    cls = _cls(LLM_PROVIDERS, conn.provider)
    return cls(_chiave(conn), conn.model)


def search_for(conn):
    cls = _cls(SEARCH_PROVIDERS, conn.provider)
    return cls(_chiave(conn))


def active_connection(user_id: int, kind: str):
    from app.models import AiConnection
    return AiConnection.query.filter_by(user_id=user_id, kind=kind, active=True).first()
