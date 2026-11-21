from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict  # JSON Schema, additionalProperties: False


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class StepResult:
    conversation: list  # conversazione aggiornata, JSON-serializzabile, formato nativo del provider
    text: str | None = None  # testo dell'assistente in questo turno
    tool_calls: list[ToolCall] = field(default_factory=list)  # vuota = l'agente ha finito


class AdapterError(Exception):
    """Messaggio sicuro da mostrare all'utente (mai la chiave)."""


class LlmAdapter(ABC):
    provider: str

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    @abstractmethod
    def start(self, user_message: str) -> list: ...

    @abstractmethod
    def step(self, conversation: list, system: str, tools: list[ToolSpec]) -> StepResult: ...

    @abstractmethod
    def add_tool_results(self, conversation: list, results: list[tuple[ToolCall, str, bool]]) -> list:
        """results: (chiamata, contenuto, is_error), tutti in un unico messaggio."""

    @abstractmethod
    def extract_json(self, prompt: str, schema: dict) -> dict: ...

    @abstractmethod
    def test(self) -> None:
        """Solleva AdapterError se la connessione non funziona."""


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str


class SearchAdapter(ABC):
    provider: str

    def __init__(self, api_key: str):
        self.api_key = api_key

    @abstractmethod
    def search(self, query: str, n: int) -> list[SearchResult]: ...

    @abstractmethod
    def test(self) -> None: ...
