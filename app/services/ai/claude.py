import json
import logging

import anthropic

from app.services.ai.base import AdapterError, LlmAdapter, StepResult, ToolCall

logger = logging.getLogger(__name__)

MAX_TOKENS = 16000
# Fallback server-side: su un rifiuto dei classificatori l'API riesegue la richiesta su un altro modello.
FALLBACK = {'betas': ['server-side-fallback-2026-07-01'], 'fallbacks': 'default'}


def _rinviabili(content: list) -> list:
    """Blocchi da salvare e rimandare all'API.

    Dopo un fallback a metà output, prima dell'ultimo blocco `fallback` si tengono solo
    testo e blocchi `fallback` (thinking e tool_use del modello che ha rifiutato vanno tolti,
    e per i tool_use tolti non si manda tool_result). Il resto passa invariato.
    """
    ultimo = max((i for i, b in enumerate(content) if b['type'] == 'fallback'), default=-1)
    return [b for i, b in enumerate(content) if i >= ultimo or b['type'] in ('text', 'fallback')]


class ClaudeAdapter(LlmAdapter):
    provider = 'claude'

    def __init__(self, api_key: str, model: str):
        super().__init__(api_key, model)
        self.client = anthropic.Anthropic(api_key=api_key)

    def _chiama(self, fn, *args, **kwargs):
        # Messaggi brevi e fissi: mai str(e), che potrebbe riportare dati della richiesta.
        try:
            resp = fn(*args, **kwargs)
        except anthropic.AuthenticationError:
            raise AdapterError('Chiave API Claude non valida')
        except anthropic.PermissionDeniedError:
            raise AdapterError('Chiave API Claude senza i permessi necessari')
        except anthropic.NotFoundError:
            raise AdapterError(f'Modello Claude non trovato: {self.model}')
        except anthropic.RateLimitError:
            raise AdapterError('Limite di richieste Claude superato, riprova più tardi')
        except anthropic.APIStatusError as e:
            logger.warning('Errore API Claude HTTP %s', e.status_code)
            raise AdapterError(f'Errore API Claude (HTTP {e.status_code})')
        except anthropic.APIConnectionError:
            raise AdapterError("Impossibile contattare l'API Claude")
        if getattr(resp, 'stop_reason', None) == 'refusal':
            categoria = resp.stop_details.category if resp.stop_details else None
            raise AdapterError(f'Richiesta rifiutata dal modello (categoria: {categoria or "non specificata"})')
        if getattr(resp, 'stop_reason', None) == 'max_tokens':
            raise AdapterError('Risposta del modello troncata (limite di token raggiunto)')
        return resp

    def start(self, user_message):
        return [{'role': 'user', 'content': user_message}]

    def step(self, conversation, system, tools):
        kwargs = {}
        if tools:
            kwargs['tools'] = [{'name': t.name, 'description': t.description,
                                'input_schema': t.input_schema, 'strict': True} for t in tools]
        resp = self._chiama(self.client.beta.messages.create, model=self.model, max_tokens=MAX_TOKENS,
                            system=system, messages=conversation, output_config={'effort': 'medium'},
                            **FALLBACK, **kwargs)
        # by_alias: il blocco fallback ha il campo "from" (in Python "from_")
        content = _rinviabili([b.model_dump(mode='json', exclude_none=True, by_alias=True)
                               for b in resp.content])
        testo = '\n'.join(b['text'] for b in content if b['type'] == 'text') or None
        calls = [ToolCall(id=b['id'], name=b['name'], input=b['input'])
                 for b in content if b['type'] == 'tool_use']
        return StepResult(conversation=list(conversation) + [{'role': 'assistant', 'content': content}],
                          text=testo, tool_calls=calls)

    def add_tool_results(self, conversation, results):
        blocchi = []
        for call, contenuto, is_error in results:
            b = {'type': 'tool_result', 'tool_use_id': call.id, 'content': contenuto}
            if is_error:
                b['is_error'] = True
            blocchi.append(b)
        return list(conversation) + [{'role': 'user', 'content': blocchi}]

    def extract_json(self, prompt, schema):
        resp = self._chiama(self.client.beta.messages.create, model=self.model, max_tokens=MAX_TOKENS,
                            messages=[{'role': 'user', 'content': prompt}],
                            output_config={'format': {'type': 'json_schema', 'schema': schema}},
                            **FALLBACK)
        testo = next((b.text for b in resp.content if b.type == 'text'), None)
        try:
            return json.loads(testo)
        except (TypeError, ValueError):
            raise AdapterError('Risposta JSON non valida dal modello')

    def test(self):
        self._chiama(self.client.models.retrieve, self.model)
