"""Adattatori finti per i test (nessuna rete).

Uso:
    register_fakes()   # in setUp: aggiunge "fake" ai registri (idempotente)
    reset_fakes()      # in setUp: azzera lo stato di classe (script, received, ...)

    FakeLlm.script = [
        {'text': 'cerco', 'tool_calls': [('cerca_web', {'query': 'x'}), ('fai_domanda', {...})]},
        {'error': 'messaggio'},   # step() solleva AdapterError('messaggio')
    ]
    ... a script esaurito step() ritorna senza tool_calls (agente finito).
    FakeLlm.received: lista delle conversazioni (copie) passate a step().
    FakeLlm.json_reply: ritorno di extract_json.
    FakeSearch.results / FakeSearch.error (stringa -> AdapterError).
"""
import copy

from app.services.ai import registry
from app.services.ai.base import (AdapterError, LlmAdapter, SearchAdapter,
                                  StepResult, ToolCall)


class FakeLlm(LlmAdapter):
    provider = 'fake'
    script: list = []
    received: list = []
    json_reply: dict = {}
    test_error: str | None = None
    _n = 0

    def start(self, user_message):
        return [{'role': 'user', 'content': user_message}]

    def step(self, conversation, system, tools):
        FakeLlm.received.append(copy.deepcopy(conversation))
        if not FakeLlm.script:
            return StepResult(conversation=list(conversation), text=None, tool_calls=[])
        turno = FakeLlm.script.pop(0)
        if turno.get('error'):
            raise AdapterError(turno['error'])
        calls = []
        for nome, inp in turno.get('tool_calls', []):
            FakeLlm._n += 1
            calls.append(ToolCall(id=f'call_{FakeLlm._n}', name=nome, input=inp))
        msg = {'role': 'assistant', 'content': turno.get('text'),
               'tool_calls': [{'id': c.id, 'name': c.name, 'input': c.input} for c in calls]}
        return StepResult(conversation=list(conversation) + [msg], text=turno.get('text'), tool_calls=calls)

    def add_tool_results(self, conversation, results):
        msg = {'role': 'user', 'tool_results': [
            {'id': c.id, 'content': content, 'is_error': err} for c, content, err in results]}
        return list(conversation) + [msg]

    def extract_json(self, prompt, schema):
        return FakeLlm.json_reply

    def test(self):
        if FakeLlm.test_error:
            raise AdapterError(FakeLlm.test_error)


class FakeSearch(SearchAdapter):
    provider = 'fake'
    results: list = []
    error: str | None = None
    queries: list = []

    def search(self, query, n):
        FakeSearch.queries.append(query)
        if FakeSearch.error:
            raise AdapterError(FakeSearch.error)
        return FakeSearch.results[:n]

    def test(self):
        if FakeSearch.error:
            raise AdapterError(FakeSearch.error)


def reset_fakes():
    FakeLlm.script, FakeLlm.received, FakeLlm.json_reply = [], [], {}
    FakeLlm.test_error, FakeLlm._n = None, 0
    FakeSearch.results, FakeSearch.error, FakeSearch.queries = [], None, []


def register_fakes():
    registry.LLM_PROVIDERS['fake'] = {'cls': FakeLlm, 'models': ['fake-1', 'fake-2'], 'default_model': 'fake-1'}
    registry.SEARCH_PROVIDERS['fake'] = {'cls': FakeSearch}
