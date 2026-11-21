import json
import unittest
from unittest.mock import patch

import anthropic
import httpx2
from anthropic.types.beta import BetaMessage

from app.services.ai.base import AdapterError, ToolCall, ToolSpec
from app.services.ai.claude import ClaudeAdapter
from app.services.ai.registry import LLM_PROVIDERS

CHIAVE = 'sk-ant-segretissima'


def messaggio(content, stop_reason='tool_use', stop_details=None):
    return BetaMessage.model_validate({
        'id': 'msg_1', 'type': 'message', 'role': 'assistant', 'model': 'claude-opus-5-5',
        'stop_reason': stop_reason, 'stop_sequence': None, 'stop_details': stop_details,
        'usage': {'input_tokens': 1, 'output_tokens': 1}, 'content': content})


def errore(cls, status):
    resp = httpx2.Response(status, request=httpx2.Request('POST', 'https://api.anthropic.com/v1/messages'))
    return cls(f'errore con {CHIAVE}', response=resp, body=None)


TOOL = ToolSpec('cerca_web', 'Cerca sul web', {
    'type': 'object', 'properties': {'query': {'type': 'string'}},
    'required': ['query'], 'additionalProperties': False})


class ClaudeAdapterTestCase(unittest.TestCase):
    def setUp(self):
        p = patch('app.services.ai.claude.anthropic.Anthropic')
        self.Anthropic = p.start()
        self.addCleanup(p.stop)
        self.client = self.Anthropic.return_value
        self.llm = ClaudeAdapter(CHIAVE, 'claude-opus-5-5')

    def test_registrato(self):
        self.assertIs(LLM_PROVIDERS['claude']['cls'], ClaudeAdapter)
        self.assertEqual(LLM_PROVIDERS['claude']['default_model'], 'claude-opus-5-5')
        self.Anthropic.assert_called_once_with(api_key=CHIAVE)

    def test_step_tool_use(self):
        self.client.beta.messages.create.return_value = messaggio([
            {'type': 'thinking', 'thinking': '', 'signature': 'sig'},
            {'type': 'text', 'text': 'Cerco.'},
            {'type': 'tool_use', 'id': 'tu_1', 'name': 'cerca_web', 'input': {'query': 'python'}},
        ])
        conv = self.llm.start('trova lavoro')
        r = self.llm.step(conv, 'sistema', [TOOL])

        self.assertEqual(r.tool_calls, [ToolCall('tu_1', 'cerca_web', {'query': 'python'})])
        self.assertEqual(r.text, 'Cerco.')
        self.assertEqual(len(r.conversation), 2)
        self.assertEqual(len(conv), 1)  # input non modificato
        ass = r.conversation[1]
        self.assertEqual(ass['role'], 'assistant')
        self.assertEqual(ass['content'][0], {'type': 'thinking', 'thinking': '', 'signature': 'sig'})
        json.dumps(r.conversation)

        kw = self.client.beta.messages.create.call_args.kwargs
        self.assertEqual(kw['model'], 'claude-opus-5-5')
        self.assertEqual(kw['max_tokens'], 16000)
        self.assertEqual(kw['system'], 'sistema')
        self.assertEqual(kw['messages'], conv)
        self.assertEqual(kw['output_config'], {'effort': 'medium'})
        self.assertEqual(kw['betas'], ['server-side-fallback-2026-07-01'])
        self.assertEqual(kw['fallbacks'], 'default')
        self.assertNotIn('tool_choice', kw)
        self.assertNotIn('thinking', kw)
        self.assertEqual(kw['tools'], [{'name': 'cerca_web', 'description': 'Cerca sul web',
                                        'input_schema': TOOL.input_schema, 'strict': True}])

    def test_step_fine(self):
        self.client.beta.messages.create.return_value = messaggio(
            [{'type': 'text', 'text': 'Fatto'}], stop_reason='end_turn')
        r = self.llm.step(self.llm.start('x'), 's', [TOOL])
        self.assertEqual((r.text, r.tool_calls), ('Fatto', []))

    def test_step_fallback_blocchi_rinviabili(self):
        # dopo un fallback a metà output: via thinking/tool_use prima dell'ultimo blocco fallback,
        # il blocco fallback resta al suo posto con la chiave "from" (alias)
        self.client.beta.messages.create.return_value = messaggio([
            {'type': 'thinking', 'thinking': '', 'signature': 'a'},
            {'type': 'text', 'text': 'parziale'},
            {'type': 'tool_use', 'id': 'tu_vecchio', 'name': 'cerca_web', 'input': {'query': 'a'}},
            {'type': 'fallback', 'from': {'model': 'claude-opus-5-5'}, 'to': {'model': 'claude-opus-4-8'},
             'trigger': {'type': 'refusal'}},
            {'type': 'thinking', 'thinking': '', 'signature': 'b'},
            {'type': 'tool_use', 'id': 'tu_nuovo', 'name': 'cerca_web', 'input': {'query': 'b'}},
        ])
        r = self.llm.step(self.llm.start('x'), 's', [TOOL])
        content = r.conversation[-1]['content']
        self.assertEqual([b['type'] for b in content], ['text', 'fallback', 'thinking', 'tool_use'])
        self.assertIn('from', content[1])
        self.assertNotIn('from_', content[1])
        self.assertEqual([c.id for c in r.tool_calls], ['tu_nuovo'])

    def test_add_tool_results_un_solo_messaggio(self):
        conv = [{'role': 'user', 'content': 'x'}]
        a, b = ToolCall('t1', 'n', {}), ToolCall('t2', 'n', {})
        out = self.llm.add_tool_results(conv, [(a, 'ok', False), (b, 'rotto', True)])
        self.assertEqual(len(out), 2)
        self.assertEqual(len(conv), 1)
        self.assertEqual(out[1], {'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': 't1', 'content': 'ok'},
            {'type': 'tool_result', 'tool_use_id': 't2', 'content': 'rotto', 'is_error': True},
        ]})

    def test_refusal(self):
        self.client.beta.messages.create.return_value = messaggio(
            [], stop_reason='refusal', stop_details={'type': 'refusal', 'category': 'cyber', 'explanation': None})
        with self.assertRaises(AdapterError) as cm:
            self.llm.step(self.llm.start('x'), 's', [TOOL])
        self.assertIn('cyber', str(cm.exception))

    def test_max_tokens(self):
        self.client.beta.messages.create.return_value = messaggio(
            [{'type': 'text', 'text': 'tronc'}], stop_reason='max_tokens')
        with self.assertRaises(AdapterError):
            self.llm.step(self.llm.start('x'), 's', [TOOL])

    def test_errori_sdk_senza_chiave(self):
        casi = [errore(anthropic.AuthenticationError, 401), errore(anthropic.RateLimitError, 429),
                errore(anthropic.NotFoundError, 404), errore(anthropic.InternalServerError, 500),
                anthropic.APIConnectionError(message=f'giu {CHIAVE}', request=httpx2.Request('POST', 'https://x'))]
        for exc in casi:
            self.client.beta.messages.create.side_effect = exc
            with self.assertRaises(AdapterError) as cm:
                self.llm.step(self.llm.start('x'), 's', [TOOL])
            self.assertNotIn(CHIAVE, str(cm.exception))
            self.assertNotIn('sk-ant', str(cm.exception))

    def test_extract_json(self):
        self.client.beta.messages.create.return_value = messaggio(
            [{'type': 'text', 'text': '{"a": 1}'}], stop_reason='end_turn')
        schema = {'type': 'object', 'properties': {'a': {'type': 'integer'}},
                  'required': ['a'], 'additionalProperties': False}
        self.assertEqual(self.llm.extract_json('estrai', schema), {'a': 1})
        kw = self.client.beta.messages.create.call_args.kwargs
        self.assertEqual(kw['output_config']['format'], {'type': 'json_schema', 'schema': schema})
        self.assertEqual(kw['messages'], [{'role': 'user', 'content': 'estrai'}])

    def test_test_connessione(self):
        self.llm.test()
        self.client.models.retrieve.assert_called_once_with('claude-opus-5-5')
        self.client.models.retrieve.side_effect = errore(anthropic.AuthenticationError, 401)
        with self.assertRaises(AdapterError) as cm:
            self.llm.test()
        self.assertNotIn(CHIAVE, str(cm.exception))


if __name__ == '__main__':
    unittest.main()
