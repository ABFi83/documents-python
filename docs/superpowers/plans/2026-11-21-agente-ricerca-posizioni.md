# Agente di ricerca posizioni — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un agente AI (provider intercambiabile) che, partendo da criteri salvati e dai CV, cerca posizioni sul web con strumenti nostri, può fare domande all'utente, salva posizioni verificate; l'utente le vota (1–5), ne segue gli stati e i voti guidano le ricerche successive.

**Architecture:** Loop agentico nostro (`app/services/agent/runner.py`) in thread in background, sullo stile di `analyze_file`/`Process`; un'interfaccia `LlmAdapter` con un'implementazione per provider (prima: Claude) e un'interfaccia `SearchAdapter` (prima: Brave Search). Strumenti `cerca_web`, `leggi_pagina`, `salva_posizione`, `fai_domanda`; ogni salvataggio passa dai controlli nel codice. Chiavi API cifrate con Fernet nel DB.

**Tech Stack:** Flask 3, Flask-SQLAlchemy (SQLite), Marshmallow, Flask-JWT-Extended, `anthropic` SDK, `cryptography` (Fernet), `requests`, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-21-agente-ricerca-posizioni-design.md` (leggerlo prima di ogni task).

## Global Constraints

- Python 3.14, venv: `.venv\Scripts\python`. Test: `.venv\Scripts\python -m unittest discover tests`.
- Test sempre con `create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', ...})`; nessuna chiamata di rete reale nei test (adattatori finti / `unittest.mock`).
- `get_jwt_identity()` è stringa: `int(get_jwt_identity())`.
- Niente migrazioni: tabelle nuove via `db.create_all()`; nessuna colonna nuova su tabelle esistenti.
- Scritture dai thread: UPDATE condizionato per primo nella transazione, `rowcount == 0` → rollback e stop (stesso schema di `save_process` in `app/services/extract_service.py`).
- Chiavi API: mai restituite, mai loggate, mai nei messaggi d'errore. Cifratura con `ENCRYPTION_KEY` (env, letta in `app.config['ENCRYPTION_KEY']`).
- All'AI e alla ricerca non arrivano nome, cognome, email, telefono, link a profili. I nomi delle aziende delle esperienze sì.
- Nessuna libreria che unifica i provider (no LiteLLM): un adattatore per provider.
- Codice Claude: modello predefinito `claude-opus-5-5`; prima di scrivere l'adattatore invocare la skill `claude-api` e seguire le sue regole (no `tool_choice` forzato, no `budget_tokens`, gestione `stop_reason == "refusal"`, fallback server-side `fallbacks: "default"`).
- Messaggi/commenti in italiano come il resto del codice. Nessun commit se l'utente non lo chiede.

## Review Focus

1. URL salvato dall'agente con parametri di tracciamento (o `/` finale) mentre in `cerca_web` era senza: deve essere accettato (verifica su URL normalizzati da entrambe le parti). Test in Task 9.
2. Annullare o cancellare un run in `WAITING_INPUT` e poi rispondere: 409/404, nessuna scrittura; un thread in corso dopo l'annullamento non salva posizioni. Test in Task 10.
3. Turno dell'agente con più chiamate insieme, tra cui `fai_domanda`: i risultati delle altre chiamate vengono conservati e inviati insieme alla risposta dell'utente in un unico messaggio. Test in Task 10.
4. Errore del provider di ricerca o pagina illeggibile a metà run: lo strumento restituisce un errore all'agente e il run continua; errore dell'adattatore LLM: run `ERROR` con messaggio senza chiave. Test in Task 10.
5. Utente senza CV `COMPLETED`: suggerimenti vuoti e run che parte con i soli criteri. Test in Task 6 e Task 10.

---

### Task 1: Ruolo obiettivo nell'estrazione del CV

**Files:**
- Modify: `app/services/extract_service.py` (nuova `estrai_ruolo_obiettivo`, campo in `extract_info_from_text`)
- Test: `tests/test_extract_service.py`

**Interfaces:**
- Produces: `estrai_ruolo_obiettivo(text: str) -> str | None`; `Process.result["ruolo_obiettivo"]`.

- [ ] **Step 1: Test che falliscono**

```python
def test_ruolo_obiettivo_from_headline(self):
    self.assertEqual(estrai_ruolo_obiettivo(CV), 'Senior Python Engineer')

def test_ruolo_obiettivo_missing(self):
    self.assertIsNone(estrai_ruolo_obiettivo("Mario Rossi\nPROFILO\nqualcosa\n"))
```

- [ ] **Step 2:** `.venv\Scripts\python -m unittest tests.test_extract_service -v` → FAIL (`ImportError`).
- [ ] **Step 3: `estrai_ruolo_obiettivo`**: tra le prime 3 righe non vuote dopo la prima, la prima riga che non è un'intestazione di sezione (`SEZIONE`), non contiene `@` né cifre di telefono; si prende il testo prima di `·`, `|`, ` - ` o `,`, ripulito; `None` se nulla. In `extract_info_from_text` aggiungere `"ruolo_obiettivo": estrai_ruolo_obiettivo(text)` a `info`.
- [ ] **Step 4:** stessi test + `tests.test_documents` → PASS.

---

### Task 2: Cifratura chiavi e log senza segreti

**Files:**
- Create: `app/utils/crypto.py`
- Modify: `app/__init__.py` (config `ENCRYPTION_KEY` da env; `log_request_info` non logga il body per i path che iniziano con `/settings`), `requirements.txt` (+ `cryptography`, + `anthropic`)
- Test: `tests/test_crypto.py`

**Interfaces:**
- Produces: `encrypt(plain: str) -> str`, `decrypt(token: str) -> str`, eccezione `CryptoNotConfigured(Exception)`. Leggono `current_app.config['ENCRYPTION_KEY']` (chiave Fernet urlsafe base64).

- [ ] **Step 1: Test**: round trip `decrypt(encrypt('sk-abc')) == 'sk-abc'` con `ENCRYPTION_KEY = Fernet.generate_key().decode()` passato a `create_app`; senza chiave `encrypt` solleva `CryptoNotConfigured`; il token non contiene il testo in chiaro.
- [ ] **Step 2:** FAIL. **Step 3:** implementare con `cryptography.fernet.Fernet`; `pip install -r requirements.txt`. **Step 4:** PASS.

---

### Task 3: Interfacce degli adattatori, registro, adattatori finti per i test

**Files:**
- Create: `app/services/ai/__init__.py`, `app/services/ai/base.py`, `app/services/ai/registry.py`, `tests/fakes.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces (in `base.py`):

```python
@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict          # JSON Schema, additionalProperties: False

@dataclass
class ToolCall:
    id: str
    name: str
    input: dict

@dataclass
class StepResult:
    conversation: list          # conversazione aggiornata, JSON-serializzabile, formato nativo del provider
    text: str | None            # testo dell'assistente in questo turno
    tool_calls: list[ToolCall]  # vuota = l'agente ha finito

class AdapterError(Exception): ...   # messaggio sicuro da mostrare (mai la chiave)

class LlmAdapter(ABC):
    provider: str
    def __init__(self, api_key: str, model: str): ...
    def start(self, user_message: str) -> list: ...
    def step(self, conversation: list, system: str, tools: list[ToolSpec]) -> StepResult: ...
    def add_tool_results(self, conversation: list, results: list[tuple[ToolCall, str, bool]]) -> list: ...  # (chiamata, contenuto, is_error), tutti in un unico messaggio
    def extract_json(self, prompt: str, schema: dict) -> dict: ...
    def test(self) -> None: ...      # solleva AdapterError

@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str

class SearchAdapter(ABC):
    provider: str
    def __init__(self, api_key: str): ...
    def search(self, query: str, n: int) -> list[SearchResult]: ...
    def test(self) -> None: ...
```

- Produces (in `registry.py`): `LLM_PROVIDERS: dict[str, dict]` (`{"claude": {"cls": ClaudeAdapter, "models": ["claude-opus-5-5", "claude-sonnet-5-5"], "default_model": "claude-opus-5-5"}}`, voce aggiunta in Task 5), `SEARCH_PROVIDERS: dict[str, dict]` (`{"brave": {"cls": BraveSearch}}`, Task 5), `providers_info() -> dict` (`{"llm": [{"provider", "models", "default_model"}], "search": [{"provider"}]}`), `llm_for(conn) -> LlmAdapter`, `search_for(conn) -> SearchAdapter` (decifrano `conn.api_key_enc`).
- Produces (in `tests/fakes.py`): `FakeLlm(LlmAdapter)` che esegue uno script di turni (`FakeLlm.script: list[StepResult-like]` impostato dal test, registra i messaggi ricevuti in `FakeLlm.received`), `extract_json` restituisce `FakeLlm.json_reply`; `FakeSearch(SearchAdapter)` con `FakeSearch.results`. Helper `register_fakes()` che li aggiunge a `LLM_PROVIDERS["fake"]` / `SEARCH_PROVIDERS["fake"]`.

- [ ] **Step 1: Test**: `register_fakes()` poi `providers_info()` contiene `fake` in entrambe le liste; `llm_for` su una connessione `provider="fake"` restituisce un `FakeLlm` con la chiave decifrata.
- [ ] **Step 2:** FAIL. **Step 3:** implementare. **Step 4:** PASS.

---

### Task 4: Connessioni AI (modello + `/settings`)

**Files:**
- Modify: `app/models.py` (`AiConnection`), `app/schemas.py` (`AiConnectionSchema`: tutto tranne `api_key_enc`), `app/__init__.py` (registra blueprint)
- Create: `app/routes/settings.py` (blueprint `settings_bp`, prefisso `/settings`)
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `AiConnection(id, user_id, kind: 'llm'|'search', provider, model: str|None, api_key_enc, key_last4, active: bool, created_at)`; `active_connection(user_id: int, kind: str) -> AiConnection | None` (in `app/routes/settings.py` o `app/services/ai/registry.py`, a scelta, ma con questo nome).
- Rotte: `GET /settings/providers` → `providers_info()`; `GET /settings/connections`; `POST /settings/connections {kind, provider, model?, api_key, active?}` → 201; `PATCH /settings/connections/<id> {model?, api_key?, active?}`; `DELETE /settings/connections/<id>` (409 se usata da un run attivo, dopo Task 10); `POST /settings/connections/<id>/test` → `{"ok": true}` o 400 `{"ok": false, "msg": <AdapterError>}`.
- Regole: provider deve esistere in `LLM_PROVIDERS`/`SEARCH_PROVIDERS` per quel `kind` (400 altrimenti); `model` obbligatorio per `llm` (default `default_model`); attivarne una disattiva le altre dello stesso `(user_id, kind)`; la prima connessione di un tipo diventa attiva.

- [ ] **Step 1: Test** (con `register_fakes()` e `ENCRYPTION_KEY`): creazione → risposta senza `api_key`/`api_key_enc`, `key_last4 == 'cdef'` per `api_key='sk-abcdef'`; nel DB `api_key_enc != 'sk-abcdef'`; seconda connessione `llm` con `active: true` disattiva la prima; provider sconosciuto → 400; connessione di un altro utente → 404; `test` con `FakeLlm` ok → `{"ok": true}`; un `AdapterError("Chiave non valida")` → 400 con quel messaggio; il body della POST non compare nel log (`self.assertLogs` sul logger root: nessun record contiene `sk-abcdef`).
- [ ] **Step 2:** FAIL. **Step 3:** implementare. **Step 4:** PASS.

---

### Task 5: Adattatore Claude e adattatore Brave Search

**Files:**
- Create: `app/services/ai/claude.py` (`ClaudeAdapter`), `app/services/ai/brave.py` (`BraveSearch`)
- Modify: `app/services/ai/registry.py` (voci `claude`, `brave`)
- Test: `tests/test_claude_adapter.py`, `tests/test_brave.py`

**Interfaces:**
- Consumes: `LlmAdapter`, `SearchAdapter`, `ToolSpec`, `ToolCall`, `StepResult`, `AdapterError` (Task 3).
- Produces: `ClaudeAdapter(api_key, model)`, `BraveSearch(api_key)` registrati come `claude` e `brave`.

ClaudeAdapter (invocare prima la skill `claude-api`, leggere `python/claude-api/tool-use.md` e la sezione refusal/fallback di `shared/model-migration.md`):
- `anthropic.Anthropic(api_key=...)`; `step` usa `client.beta.messages.create(model, max_tokens=16000, system, tools, messages, output_config={"effort": "medium"}, betas=["server-side-fallback-2026-07-01"], fallbacks="default")`; strumenti con `strict: True`; `tool_choice` non impostato (auto).
- Conversazione salvata come `[{"role", "content": [block.model_dump(mode="json", exclude_none=True), ...]}]`: i blocchi dell'assistente (thinking compresi) vanno ripassati invariati.
- `stop_reason == "refusal"` → `AdapterError` con la categoria; eccezioni SDK (`AuthenticationError`, `RateLimitError`, `APIStatusError`, `APIConnectionError`) → `AdapterError` con messaggio breve senza chiave.
- `extract_json` con `client.messages.create(..., output_config={"format": {"type": "json_schema", "schema": schema}})`, `json.loads` del primo blocco text.
- `test()` → `client.models.retrieve(self.model)`.

BraveSearch: `GET https://api.search.brave.com/res/v1/web/search` con `params={"q": query, "count": n}`, header `X-Subscription-Token` e `Accept: application/json`, timeout 20s; risultati da `data["web"]["results"]` (`url`, `title`, `description`); errori HTTP → `AdapterError`. Verificare il formato sulla documentazione Brave prima di implementare; se la prova su query di annunci italiani è scadente, l'implementatore può proporre un'altra API mantenendo `SearchAdapter`.

- [ ] **Step 1: Test** con `unittest.mock.patch` del client/`requests.get`: `ClaudeAdapter.step` restituisce `ToolCall` per un blocco `tool_use` e conversazione con il turno assistente aggiunto; `add_tool_results` produce un unico messaggio `user` con tutti i `tool_result` (`is_error` dove vero); refusal → `AdapterError`; `AuthenticationError` → `AdapterError` il cui testo non contiene la chiave; `BraveSearch.search` mappa i risultati in `SearchResult`; HTTP 401 → `AdapterError`.
- [ ] **Step 2:** FAIL. **Step 3:** implementare. **Step 4:** PASS.

---

### Task 6: Criteri di ricerca e suggerimenti dai CV

**Files:**
- Modify: `app/models.py` (`SearchProfile`), `app/schemas.py` (`CriteriaSchema`, `SearchProfileSchema`), `app/__init__.py`
- Create: `app/routes/search_profiles.py` (blueprint, prefisso `/search-profiles`)
- Test: `tests/test_search_profiles.py`

**Interfaces:**
- Produces: `SearchProfile(id, user_id, name, criteria: JSON, created_at, updated_at)`. `criteria` validato da `CriteriaSchema`: `ruoli: list[str]`, `competenze: list[{nome: str, obbligatoria: bool}]`, `luogo: str|None`, `modalita: list['remoto'|'ibrido'|'presenza']`, `seniority: str|None`, `contratto: str|None`, `ral_min: int|None`, `lingue: list[str]`, `esclusioni: list[str]`, `max_giorni_annuncio: int = 30`, `note: str|None`.
- Rotte: CRUD `/search-profiles` (`name` obbligatorio; 400 con errori di validazione); `GET /search-profiles/suggestions` → `{"ruoli": [...], "competenze": [...]}`: ruoli = `ruolo_obiettivo` dei CV `COMPLETED` (dal più recente) + ruoli delle esperienze (più recenti prima), senza doppioni case-insensitive; competenze = nomi di `linguaggi` + `frameworks` da `somma_estrazioni` nello stesso ordine.
- `DELETE /search-profiles/<id>`: annulla un run attivo del profilo (dopo Task 10), mette `profile_id = None` sulle posizioni e sui run, poi cancella.

- [ ] **Step 1: Test**: CRUD felice; `modalita: ["spazio"]` → 400; profilo di un altro utente → 404; suggerimenti con 2 CV caricati (pattern `SyncThread` + `pdf_to_text` mockato di `tests/test_documents.py`) contengono il ruolo obiettivo e le skill; **utente senza CV → `{"ruoli": [], "competenze": []}`**.
- [ ] **Step 2:** FAIL. **Step 3:** implementare. **Step 4:** PASS.

---

### Task 7: Lettura pagine sicura

**Files:**
- Create: `app/services/agent/__init__.py`, `app/services/agent/pages.py`
- Test: `tests/test_pages.py`

**Interfaces:**
- Produces: `read_page(url: str, max_chars: int = 20000) -> str`, `PageError(Exception)` (messaggio da girare all'agente/utente).

Regole: solo `http`/`https`; host risolto con `socket.getaddrinfo`, rifiuto se un indirizzo è privato, loopback, link-local, riservato o multicast (`ipaddress`); redirect seguiti a mano (max 3), con lo stesso controllo a ogni salto; timeout 15s; lettura in streaming fino a 2 MB; HTML → testo con `html.parser` della stdlib ignorando `script`/`style`/`noscript`, spazi compressi; troncato a `max_chars`. Status ≥ 400 → `PageError("Pagina non leggibile (HTTP <code>)")`.

- [ ] **Step 1: Test** (mock di `socket.getaddrinfo` e `requests.get`): `http://127.0.0.1/` e `http://10.0.0.5/` → `PageError`; `ftp://x` → `PageError`; redirect verso `http://169.254.169.254/` → `PageError`; HTML con `<script>` → testo senza script; HTTP 403 → `PageError`.
- [ ] **Step 2:** FAIL. **Step 3:** implementare. **Step 4:** PASS.

---

### Task 8: Posizioni, voti, stati, controllo dei motivi

**Files:**
- Modify: `app/models.py` (`Position`, `PositionEvent`), `app/schemas.py`, `app/__init__.py`
- Create: `app/services/positions.py`, `app/routes/positions.py` (blueprint, prefisso `/positions`)
- Test: `tests/test_positions.py`

**Interfaces:**
- Produces (modelli): `Position` con i campi del §6 della spec più `url_norm` e `key_norm` (indicizzati), `stato` default `da_valutare`; `PositionEvent(id, position_id, da_stato, a_stato, interesse, nota, created_at)`.
- Produces (`app/services/positions.py`):
  - `normalize_url(url: str) -> str`: host minuscolo, niente frammento, rimossi `utm_*`, `gclid`, `fbclid`, `ref`, `trk`, `trackingId`, parametri restanti ordinati, niente `/` finale (tranne la radice).
  - `normalize_key(azienda: str, titolo: str) -> str`: casefold, punteggiatura → spazio, spazi compressi, `"<azienda>|<titolo>"`.
  - `find_duplicate(user_id: int, url: str, azienda: str, titolo: str) -> Position | None`.
  - `TRANSITIONS = {'da_valutare': {'promossa', 'bocciata'}, 'promossa': {'candidato', 'non_candidato', 'bocciata', 'da_valutare'}, 'bocciata': {'da_valutare', 'promossa'}, 'non_candidato': {'candidato', 'promossa'}, 'candidato': {'accettato', 'rifiutato', 'promossa'}, 'accettato': {'candidato'}, 'rifiutato': {'candidato'}}`.
  - `classify_reason(motivo: str, adapter: LlmAdapter | None) -> dict` → `{"tipo": "generico"|"annuncio"|"preferenza", "preferenza": str|None}`; con adattatore usa `extract_json`; senza: meno di 4 parole → `generico`, altrimenti `annuncio`.
- Rotte:
  - `GET /positions?stato=&profile_id=&run_id=&origine=` (più recenti prima); `GET /positions/<id>` con `eventi`.
  - `POST /positions/<id>/vote {interesse: 1..5}` → aggiorna e crea evento (`da_stato == a_stato`).
  - `POST /positions/<id>/status {stato, nota?, motivo?, conferma_generico?}`: 409 se `interesse` è null ("prima il voto"); 400 se transizione non in `TRANSITIONS`; `bocciata` senza `motivo` → 400; se c'è `motivo` lo classifica con l'adattatore LLM attivo (o fallback): `generico` senza `conferma_generico` → 422 `{"code": "motivo_generico", "msg": ...}` e niente salvato; altrimenti salva `motivo`, `motivo_tipo`, `motivo_preferenza`, stato ed evento.
  - `DELETE /positions/<id>`.

- [ ] **Step 1: Test**: `normalize_url('https://Jobs.Example.com/a/?utm_source=x&id=3#top') == 'https://jobs.example.com/a?id=3'`; `normalize_key('ACME S.p.A.', 'Dev  Python') == normalize_key('acme spa', 'dev python')` (decidere e fissare nel test il trattamento di "S.p.A."); cambio stato senza voto → 409; `da_valutare → candidato` → 400; bocciatura senza motivo → 400; motivo "no" senza conferma → 422 e stato invariato, con `conferma_generico: true` → salvato con `motivo_tipo == 'generico'`; motivo classificato `preferenza` dal `FakeLlm` → `motivo_preferenza` salvato; ogni voto/cambio crea un `PositionEvent`; posizione di altro utente → 404.
- [ ] **Step 2:** FAIL. **Step 3:** implementare. **Step 4:** PASS.

---

### Task 9: Contesto per l'agente (profilo senza dati personali + riassunto valutazioni)

**Files:**
- Create: `app/services/agent/context.py`, `app/services/agent/prompt.py`
- Test: `tests/test_agent_context.py`

**Interfaces:**
- Consumes: `somma_estrazioni`, `Position`, `SearchProfile`, `normalize_url`.
- Produces:
  - `profile_context(user_id: int) -> dict` → `{"ruoli_obiettivo": [...], "esperienze": [{"ruolo", "azienda", "start_date", "end_date"}], "skill": [...], "anni_esperienza": int|None}` dai CV `COMPLETED`. Niente `nome`, `cognome`, `description`.
  - `build_feedback(user_id: int, profile_id: int | None) -> dict` → `{"positivi": [...], "negativi": [...], "preferenze_da_evitare": [{"testo", "peso"}], "url_gia_visti": [...]}`, ogni esempio `{"titolo", "azienda", "stato", "interesse", "peso"}`.
  - Pesi (valori fissati qui, regole dalla spec §7): positivi interesse 5 → 1.0, 4 → 0.6, `candidato` 1.3, `accettato` 1.5; negativi interesse 1 → 1.0, 2 → 0.6, `non_candidato` con interesse ≤ 2 → 0.3; moltiplicatore 1.0 stesso profilo, 0.5 altri; preferenze (`motivo_tipo == 'preferenza'`, raggruppate per `motivo_preferenza` casefold) peso 1.0 stesso profilo / 0.5 altri, +0.5 per ogni ripetizione, massimo 2.0; esclusi `generico`, `annuncio`, `rifiutato`. Massimo 10 positivi, 10 negativi, 15 preferenze, ordinati per peso.
  - `SYSTEM_PROMPT: str` (costante, nessun dato variabile) e `initial_message(criteria: dict, profile: dict, feedback: dict) -> str`. Il prompt spiega gli strumenti, chiede posizioni pubblicate da non più di `max_giorni_annuncio` giorni, di salvare solo pagine viste, di usare `fai_domanda` quando un criterio è ambiguo o in conflitto, di trattare i pesi > 1 come requisiti forti.

- [ ] **Step 1: Test**: con un CV il cui result contiene `nome: "Mario"`, `cognome: "Rossi"` e un'esperienza con `description` contenente `mario@example.com`, `json.dumps(profile_context(1))` non contiene `Mario`, `Rossi` né `@`; contiene l'azienda; preferenza ripetuta 2 volte nello stesso profilo → peso 1.5; preferenza di un altro profilo → 0.5; posizione `rifiutato` non è in nessuna lista di esempi ma il suo URL è in `url_gia_visti`; motivo `generico` ignorato.
- [ ] **Step 2:** FAIL. **Step 3:** implementare. **Step 4:** PASS.

---

### Task 10: Run dell'agente (loop, strumenti, domande, annullamento)

**Files:**
- Modify: `app/models.py` (`SearchRun`, enum `RunStatus`), `app/schemas.py`, `app/__init__.py` (config `AGENT_MAX_STEPS=30`, `AGENT_MAX_SEARCHES=15`, `AGENT_MAX_PAGES=25`, `AGENT_MAX_SAVED=20`), `app/routes/search_profiles.py` (avvio/elenco run), `app/routes/settings.py` (409 su delete se in uso)
- Create: `app/services/agent/runner.py`, `app/services/agent/tools.py`, `app/routes/runs.py` (blueprint, prefisso `/runs`)
- Test: `tests/test_agent_runner.py`

**Interfaces:**
- Consumes: `llm_for`, `search_for`, `active_connection`, `read_page`, `find_duplicate`, `normalize_url`, `normalize_key`, `profile_context`, `build_feedback`, `SYSTEM_PROMPT`, `initial_message`.
- Produces:
  - `RunStatus`: `PENDING`, `RUNNING`, `WAITING_INPUT`, `COMPLETED`, `ERROR`, `CANCELLED`.
  - `SearchRun(id, user_id, profile_id, llm_connection_id, search_connection_id, status, question, conversation: JSON, pending_results: JSON, verified_urls: JSON (lista di URL normalizzati), counters: JSON {"ricerche", "pagine_lette", "salvate", "scartate": {"link_non_verificato", "doppione", "gia_valutata"}}, steps, error_message, start_date, end_date)`.
  - `TOOLS: list[ToolSpec]` in `tools.py`: `cerca_web {query: str, max_risultati: int 1..10}`, `leggi_pagina {url: str}`, `salva_posizione {url, titolo, azienda, luogo?, modalita?, descrizione?, requisiti?, data_pubblicazione?, fonte?, punteggio: int 0..100, motivazione: str, skill_presenti: list[str], skill_mancanti: list[str]}`, `fai_domanda {domanda: str}`.
  - `save_run(run_id: int, expected: RunStatus, **values) -> bool` in `runner.py`: UPDATE condizionato `WHERE id = run_id AND status = expected`, rollback se 0 righe.
  - `run_agent(app, run_id: int) -> None`: target del thread per avvio e ripresa.
- Rotte: `POST /search-profiles/<id>/runs` → 202 (400 senza connessioni attive `llm` e `search`; 409 se l'utente ha già un run `PENDING`/`RUNNING`/`WAITING_INPUT`); `GET /search-profiles/<id>/runs`; `GET /runs/<id>` (con le posizioni del run); `POST /runs/<id>/answer {testo}` (409 se non `WAITING_INPUT`; passa a `RUNNING` con `save_run(..., expected=WAITING_INPUT)` e riavvia il thread); `POST /runs/<id>/cancel` (409 se già concluso); `DELETE /runs/<id>` (annulla se attivo, `run_id = None` sulle posizioni).

Comportamento del loop (`run_agent`):
1. Se `conversation` è vuota: `adapter.start(initial_message(...))`. Se ci sono `pending_results` e una risposta: `add_tool_results` con i risultati in sospeso + la risposta come risultato di `fai_domanda`, in un unico messaggio; svuota `pending_results`.
2. Ciclo: se `steps >= AGENT_MAX_STEPS` → `COMPLETED`. `adapter.step(...)`; nessuna `tool_call` → `COMPLETED`. Per ogni chiamata esegue lo strumento:
   - `cerca_web`: oltre `AGENT_MAX_SEARCHES` → errore "limite ricerche raggiunto"; altrimenti `search.search`, aggiunge gli URL normalizzati a `verified_urls`; `AdapterError` → risultato con `is_error`.
   - `leggi_pagina`: oltre limite → errore; `read_page`; `PageError` → `is_error`; in caso di successo aggiunge l'URL normalizzato a `verified_urls`.
   - `salva_posizione`: oltre `AGENT_MAX_SAVED` → errore; `normalize_url(url)` non in `verified_urls` → rifiuto `link_non_verificato`; `find_duplicate` → `gia_valutata` se la trovata ha `interesse` non null o stato ≠ `da_valutare`, altrimenti `doppione`; altrimenti crea `Position(origine='agente', run_id, profile_id)`. Contatori aggiornati.
   - `fai_domanda`: ricordata; le altre chiamate dello stesso turno si eseguono comunque e i loro risultati vanno in `pending_results`.
3. Fine turno: se c'era `fai_domanda` → `save_run(expected=RUNNING, status=WAITING_INPUT, question=..., conversation=..., pending_results=...)` e il thread termina; altrimenti `add_tool_results` e si salva `conversation`/contatori/`steps` + le posizioni nuove nella **stessa transazione** dopo `save_run(expected=RUNNING, ...)`; se `save_run` restituisce False (annullato/cancellato) → stop senza scrivere.
4. `AdapterError` dall'LLM → `ERROR` con `error_message = str(e)[:200]`; eccezione inattesa → `ERROR` con messaggio generico e log dello stack.

- [ ] **Step 1: Test** (`register_fakes()`, connessioni fake attive, thread sincrono come `SyncThread`):
  - run completo: `FakeLlm` chiama `cerca_web` → `salva_posizione` con l'URL del risultato + `?utm_source=x` → fine: 1 posizione salvata, `counters.salvate == 1`, run `COMPLETED`;
  - `salva_posizione` con URL mai visto → posizione non creata, `scartate.link_non_verificato == 1`, l'agente riceve un risultato con `is_error`;
  - doppione (stessa azienda+titolo, URL diverso) → `doppione`; posizione già votata → `gia_valutata`;
  - turno con `cerca_web` + `fai_domanda` → run `WAITING_INPUT` con `question`; `POST /runs/<id>/answer` → `FakeLlm.received` mostra un unico messaggio con il risultato di `cerca_web` e la risposta; run `COMPLETED`;
  - `cancel` in `WAITING_INPUT` poi `answer` → 409; cancellazione del run tra due passi (il test cancella dentro `FakeSearch.search`) → nessuna posizione salvata da quel passo;
  - `FakeSearch` che solleva `AdapterError` → l'agente riceve `is_error` e il run continua; `FakeLlm` che solleva `AdapterError("Chiave non valida")` → `ERROR` con quel messaggio;
  - secondo avvio con un run attivo → 409; avvio senza connessione `search` attiva → 400;
  - utente senza CV: il run parte e `FakeLlm.received[0]` contiene i criteri;
  - limite: `FakeLlm` che chiama sempre `cerca_web` → al passo `AGENT_MAX_STEPS` (impostato a 3 nel test) run `COMPLETED`.
- [ ] **Step 2:** FAIL. **Step 3:** implementare. **Step 4:** PASS (tutta la suite).

---

### Task 11: Inserimento manuale di una posizione

**Files:**
- Modify: `app/routes/positions.py`, `app/services/positions.py` (`POSITION_SCHEMA`, `extract_position(adapter, text, url) -> dict`)
- Test: `tests/test_manual_position.py`

**Interfaces:**
- Consumes: `read_page`, `PageError`, `active_connection`, `llm_for`, `find_duplicate`.
- Produces: `POST /positions/manual {url?, testo?, stato_iniziale? = 'candidato', interesse?}`:
  - né `url` né `testo` → 400; nessuna connessione LLM attiva → 400;
  - `stato_iniziale` diverso da `da_valutare` senza `interesse` → 409 ("prima il voto");
  - con solo `url`: `read_page`; `PageError` → 422 `{"code": "pagina_non_leggibile", "msg": "Incolla il testo dell'annuncio"}`;
  - estrazione con `adapter.extract_json(prompt, POSITION_SCHEMA)` (titolo, azienda obbligatori + campi facoltativi del §6);
  - doppione → 200 con la posizione esistente e `"duplicato": true`; altrimenti 201, `origine = 'manuale'`, evento iniziale nello storico.

- [ ] **Step 1: Test**: url leggibile (mock `read_page`) → 201 con campi da `FakeLlm.json_reply`, stato `candidato`; pagina non leggibile → 422 con `code`; testo incollato → 201; doppione → 200 `duplicato: true`; `stato_iniziale: 'candidato'` senza `interesse` → 409.
- [ ] **Step 2:** FAIL. **Step 3:** implementare. **Step 4:** PASS (tutta la suite).

---

### Task 12: Documentazione e brief per il FE

**Files:**
- Modify: `CLAUDE.md` (sezione sull'agente: file, flusso run, regola `save_run`, adattatori, `ENCRYPTION_KEY`)
- Create: `docs/fe/2026-11-21-agente-ricerca-fe-brief.md`

- [ ] **Step 1:** generare esempi di risposta reali per ogni rotta nuova con il test client (come fatto per lo storico CV) e scrivere il brief per il Claude del FE: sezioni Impostazioni AI, Criteri di ricerca (con suggerimenti), Ricerche (avvio, stato, domanda e risposta, annullamento, polling), Posizioni (filtri, voto, stati con lo schema delle transizioni, motivo generico con 422 e conferma, storico), Inserimento manuale (422 → campo testo), codici d'errore 400/404/409/422 e cosa mostrare; elenco "Da implementare nel FE".
- [ ] **Step 2:** tutta la suite passa; avvio di `run.py` senza errori con `ENCRYPTION_KEY` impostata.
