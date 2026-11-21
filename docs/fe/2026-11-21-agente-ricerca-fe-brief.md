# Brief FE: agente di ricerca posizioni

Il backend ora ha un agente AI che cerca offerte di lavoro sul web in base a dei criteri, salva le posizioni trovate e l'utente le valuta (voto, stato, motivo). Questo documento descrive le API e cosa deve mostrare la UI. Gli esempi JSON sono risposte reali del backend (generate con il test client; id e date sono di esempio, le chiavi sono nell'ordine alfabetico in cui le restituisce Flask).

Convenzioni valide per tutte le rotte:

- Header `Authorization: Bearer <token>` su ogni chiamata (senza: `401 {"msg": "Missing Authorization Header"}`).
- Gli errori hanno sempre `{"msg": "..."}` (testo italiano, mostrabile all'utente). Alcuni 422/502 hanno anche `code`: il FE ragiona sul `code`, non sul testo.
- Le date sono ISO 8601 senza fuso (UTC), es. `2026-11-21T13:30:20.568291`.
- Ogni risorsa è dell'utente loggato: l'id di un altro utente dà 404.

---

## 1. Impostazioni AI

L'utente configura due connessioni: una **llm** (il modello che ragiona) e una **search** (il motore di ricerca web). Servono entrambe attive per avviare una ricerca. La chiave API si inserisce una volta e **non viene mai restituita**: del segreto si vede solo `key_last4` (ultime 4 cifre).

### GET /settings/providers

Elenco di provider e modelli selezionabili (popola le select).

```json
{
  "llm": [
    {
      "default_model": "claude-opus-5-5",
      "models": ["claude-opus-5-5", "claude-sonnet-5-5"],
      "provider": "claude"
    }
  ],
  "search": [
    {"provider": "brave"}
  ]
}
```

### GET /settings/connections

Lista delle connessioni dell'utente (200). Esempio (nomi provider/modelli reali):

```json
[
  {
    "active": true,
    "created_at": "2026-11-21T13:30:20.118651",
    "id": 1,
    "key_last4": "abcd",
    "kind": "llm",
    "model": "claude-sonnet-5-5",
    "provider": "claude"
  },
  {
    "active": true,
    "created_at": "2026-11-21T13:30:20.123614",
    "id": 2,
    "key_last4": "9876",
    "kind": "search",
    "model": null,
    "provider": "brave"
  },
  {
    "active": false,
    "created_at": "2026-11-21T13:30:20.126096",
    "id": 3,
    "key_last4": "5555",
    "kind": "llm",
    "model": "claude-opus-5-5",
    "provider": "claude"
  }
]
```

Per ogni `kind` c'è al massimo una connessione `active`. La UI mostra la chiave come `••••abcd`.

### POST /settings/connections

Body:

| campo | note |
|---|---|
| `kind` | obbligatorio: `"llm"` o `"search"` |
| `provider` | obbligatorio: uno di `/settings/providers` |
| `api_key` | obbligatorio, stringa |
| `model` | solo per `llm`; se omesso si usa il `default_model`. Per `search` è `null` |
| `active` | facoltativo; la prima connessione di un `kind` diventa attiva da sola. `true` disattiva le altre dello stesso kind |

Risposta `201`: l'oggetto connessione (stessa forma della lista). Errori `400` (`msg`):

- `"kind deve essere llm o search"`, `"Provider non supportato: x"`, `"api_key obbligatoria"`, `"Modello non supportato: x"`
- `"Cifratura non configurata (ENCRYPTION_KEY)"`: il server non ha la variabile `ENCRYPTION_KEY`. Non è un errore dell'utente: mostra "Il server non è configurato per salvare le chiavi, contatta l'amministratore" e non far riprovare.

### PATCH /settings/connections/<id>

Body, tutti facoltativi: `model` (solo `llm`), `api_key` (sostituisce la chiave, aggiorna `key_last4`), `active` (`true` attiva e disattiva le altre dello stesso kind; `false` disattiva). Risposta `200` con la connessione. `400` come sopra, `404 {"msg": "Connection not found"}`.

Per "cambia chiave" mostra un campo vuoto (mai pre-compilato) e invia `api_key` solo se compilato.

### DELETE /settings/connections/<id>

`200 {"id": 3, "msg": "Connection deleted"}`. `404` se non esiste. `409 {"msg": "Connessione in uso da una ricerca attiva: attendi la fine o annullala"}` se una ricerca in corso la sta usando: mostra il messaggio e, se utile, rimanda alla ricerca.

### POST /settings/connections/<id>/test

Senza body: prova la connessione con la chiave salvata.

- `200 {"ok": true}` -> mostra "Connessione riuscita".
- `400 {"ok": false, "msg": "Chiave API non valida"}` -> mostra `msg` (il testo è sicuro, non contiene la chiave). Puo' valere anche `"Chiave API non decifrabile: reinseriscila nelle impostazioni"` o `"Cifratura non configurata sul server"`.
- `404` se la connessione non esiste.

### Cosa mostra la UI

- Due sezioni (AI / Ricerca web), ciascuna con la lista connessioni, badge "attiva", pulsanti Test, Attiva, Modifica, Elimina e "Aggiungi".
- Se manca una connessione attiva di un kind, banner nella pagina ricerche: "Configura una connessione AI e una di ricerca nelle impostazioni" (l'avvio di una ricerca darebbe 400).

---

## 2. Criteri di ricerca (profili di ricerca)

Un profilo = nome + criteri. Si possono avere più profili (es. "Backend Milano", "Remoto full").

### Forma dei criteri

| campo | tipo | default |
|---|---|---|
| `ruoli` | lista di stringhe | `[]` |
| `competenze` | lista di `{"nome": str, "obbligatoria": bool}` (`obbligatoria` default `false`) | `[]` |
| `luogo` | stringa o `null` | `null` |
| `modalita` | lista con valori ammessi `"remoto"`, `"ibrido"`, `"presenza"` | `[]` |
| `seniority` | stringa o `null` | `null` |
| `contratto` | stringa o `null` | `null` |
| `ral_min` | intero o `null` | `null` |
| `lingue` | lista di stringhe | `[]` |
| `esclusioni` | lista di stringhe (cose da evitare) | `[]` |
| `max_giorni_annuncio` | intero | `30` |
| `note` | stringa o `null` | `null` |

Tutti i campi di `criteria` sono facoltativi (i mancanti prendono il default); `name` è obbligatorio (1-100 caratteri).

### POST /search-profiles

Body: `{"name": "Backend Milano", "criteria": {...}}`. Risposta `201`:

```json
{
  "created_at": "2026-11-21T13:30:20.568291",
  "criteria": {
    "competenze": [
      {"nome": "Python", "obbligatoria": true},
      {"nome": "Django", "obbligatoria": false}
    ],
    "contratto": null,
    "esclusioni": ["consulenza"],
    "lingue": ["italiano"],
    "luogo": "Milano",
    "max_giorni_annuncio": 30,
    "modalita": ["ibrido", "remoto"],
    "note": null,
    "ral_min": 45000,
    "ruoli": ["Backend Developer"],
    "seniority": "senior"
  },
  "id": 1,
  "name": "Backend Milano",
  "updated_at": "2026-11-21T13:30:20.568294"
}
```

`400` se i dati non sono validi:

```json
{
  "errors": {
    "criteria": {"modalita": {"0": ["Must be one of: remoto, ibrido, presenza."]}},
    "name": ["Missing data for required field."]
  },
  "msg": "Dati non validi"
}
```

Mostra `msg` e, se vuoi, associa `errors` ai campi (le chiavi sono i nomi dei campi; le liste hanno come chiave l'indice).

### Altre rotte

- `GET /search-profiles` -> `200` lista di profili (stessa forma sopra).
- `GET /search-profiles/<id>` -> `200` profilo, `404 {"msg": "Profile not found"}`.
- `PUT /search-profiles/<id>` -> **sostituzione completa** (invia sempre `name` e tutti i criteri, i mancanti tornano al default). `200` profilo aggiornato, `400`, `404`.
- `DELETE /search-profiles/<id>` -> `200 {"id": 2, "msg": "Profile deleted"}`. Le posizioni e i run del profilo restano (con `profile_id` a `null`); un run attivo del profilo viene annullato. Chiedi conferma all'utente.

### GET /search-profiles/suggestions

Suggerimenti ricavati dai CV analizzati (solo quelli `COMPLETED`), per pre-compilare ruoli e competenze:

```json
{
  "competenze": ["Java", "Python", "Django", "Spring Boot"],
  "ruoli": ["backend developer", "Developer", "Analista"]
}
```

Senza CV: `{"competenze": [], "ruoli": []}`. Mostrali come chip cliccabili accanto ai campi "Ruoli" e "Competenze" del form (un clic aggiunge il valore ai criteri; le competenze suggerite entrano con `obbligatoria: false`).

### Cosa mostra la UI

Lista profili con "Nuovo", "Modifica", "Elimina", e per ciascuno il pulsante "Avvia ricerca" (sezione 3). Il form ha i campi sopra; `modalita` come multi-selezione dei tre valori; `competenze` come lista con flag "obbligatoria".

---

## 3. Ricerche (run dell'agente)

Un run è una ricerca in background: l'agente cerca, legge pagine, salva posizioni, ogni tanto può **chiedere qualcosa all'utente**. Il FE avvia e poi fa **polling**.

### Stati del run

```
PENDING -> RUNNING -> COMPLETED
              |  ^
              v  |
        WAITING_INPUT        (l'agente ha una domanda)

RUNNING / WAITING_INPUT / PENDING -> CANCELLED   (annullato dall'utente)
RUNNING -> ERROR                                   (vedi error_message)
```

Stati "attivi" (la ricerca non è finita): `PENDING`, `RUNNING`, `WAITING_INPUT`. Stati finali: `COMPLETED`, `ERROR`, `CANCELLED`. Ogni utente può avere **un solo run attivo** alla volta.

### POST /search-profiles/<profile_id>/runs

Senza body. Risposta `202` con il run appena creato (l'agente parte in background):

```json
{
  "counters": {
    "pagine_lette": 0,
    "ricerche": 0,
    "salvate": 0,
    "scartate": {"doppione": 0, "gia_valutata": 0, "link_non_verificato": 0}
  },
  "end_date": null,
  "error_message": null,
  "id": 1,
  "llm_connection_id": 1,
  "profile_id": 1,
  "question": null,
  "search_connection_id": 2,
  "start_date": "2026-11-21T13:30:20.585881",
  "status": "PENDING",
  "steps": 0
}
```

Errori:

- `400 {"msg": "Nessuna connessione AI (llm) attiva: configurala nelle impostazioni"}` (oppure "...di ricerca (search)...") -> rimanda alle impostazioni.
- `404 {"msg": "Profile not found"}`.
- `409 {"msg": "Hai già una ricerca in corso"}` -> mostra il messaggio e porta l'utente al run attivo (trovalo con `GET /search-profiles/<id>/runs`, il primo con stato attivo).

### GET /runs/<id> (polling)

Ogni 2-3 secondi finché lo stato è attivo. Contiene il run più le posizioni salvate finora in `positions` (forma completa della posizione: sezione 4).

```json
{
  "counters": {
    "pagine_lette": 0,
    "ricerche": 1,
    "salvate": 2,
    "scartate": {"doppione": 1, "gia_valutata": 0, "link_non_verificato": 0}
  },
  "end_date": "2026-11-21T13:30:20.607071",
  "error_message": null,
  "id": 1,
  "llm_connection_id": 1,
  "positions": [
    {
      "azienda": "Acme",
      "created_at": "2026-11-21T13:30:20.605659",
      "data_pubblicazione": null,
      "descrizione": null,
      "fonte": "jobs.example.it",
      "id": 1,
      "interesse": null,
      "luogo": "Milano",
      "modalita": "ibrido",
      "motivazione_ai": "Python e Django richiesti, ibrido a Milano",
      "motivo": null,
      "motivo_preferenza": null,
      "motivo_tipo": null,
      "origine": "agente",
      "profile_id": 1,
      "punteggio_ai": 82,
      "requisiti": null,
      "run_id": 1,
      "skill_mancanti": ["Kubernetes"],
      "skill_presenti": ["Python", "Django"],
      "stato": "da_valutare",
      "titolo": "Backend Developer",
      "url": "https://jobs.example.it/annuncio/42",
      "user_id": 1
    }
  ],
  "profile_id": 1,
  "question": null,
  "search_connection_id": 2,
  "start_date": "2026-11-21T13:30:20.585881",
  "status": "COMPLETED",
  "steps": 5
}
```

(la seconda posizione, "Python Developer - Beta Srl", è omessa per brevita'). `404 {"msg": "Run not found"}`.

Contatori da mostrare durante e dopo la ricerca:

- `counters.ricerche`: ricerche web fatte; `counters.pagine_lette`: pagine lette; `counters.salvate`: posizioni salvate.
- `counters.scartate`: posizioni che l'agente ha provato a salvare ma il backend ha scartato: `doppione` (già presente), `gia_valutata` (l'utente l'aveva già valutata), `link_non_verificato` (URL non verificato). Utile come riga di dettaglio ("2 salvate, 1 scartata come doppione").
- `steps`: passi dell'agente (informativo). C'è un limite di passi per run: vicino al limite l'agente viene invitato a chiudere con un riepilogo e non fa più domande, quindi un run arriva sempre a `COMPLETED` (mai fermo in `WAITING_INPUT` per il limite). `start_date` / `end_date` (null finché attivo) per la durata.

### Stato WAITING_INPUT: domanda e risposta

Quando l'agente ha bisogno di un chiarimento il run passa a `WAITING_INPUT` e `question` contiene il testo:

```json
{
  "counters": {"pagine_lette": 0, "ricerche": 1, "salvate": 0, "scartate": {"doppione": 0, "gia_valutata": 0, "link_non_verificato": 0}},
  "end_date": null,
  "error_message": null,
  "id": 1,
  "llm_connection_id": 1,
  "positions": [],
  "profile_id": 1,
  "question": "Preferisci ruoli ibridi o full remote?",
  "search_connection_id": 2,
  "start_date": "2026-11-21T13:30:20.585881",
  "status": "WAITING_INPUT",
  "steps": 2
}
```

Il FE mostra la domanda con un campo di testo libero e "Invia". **Leggi `question` solo quando `status === "WAITING_INPUT"`** (in altri stati può contenere un residuo, es. dopo l'annullamento).

#### POST /runs/<id>/answer

Body: `{"testo": "Preferisco ibrido"}`. Risposta `202` con il run, ora `RUNNING` e `question: null`; riprendi il polling.

- `400 {"msg": "testo obbligatorio"}` (vuoto o solo spazi).
- `409 {"msg": "Il run non è in attesa di una risposta"}` (già risposto, annullato o concluso): ricarica il run e mostra lo stato attuale.
- `404`.

### POST /runs/<id>/cancel

Senza body. Annulla un run attivo. `200` con il run (`status: "CANCELLED"`, `end_date` valorizzata). Le posizioni già salvate restano. `409 {"msg": "Run già concluso"}` se non è più attivo (ricarica e mostra lo stato).

### DELETE /runs/<id>

`200 {"id": 3, "msg": "Run deleted"}`. Le posizioni trovate dal run **restano** (con `run_id: null`). Funziona anche su un run attivo (lo ferma). Chiedi conferma.

### GET /search-profiles/<profile_id>/runs

Storico dei run del profilo, più recenti prima (200, lista di run **senza** `positions`). `404 {"msg": "Profile not found"}`.

```json
[
  {
    "counters": {"pagine_lette": 0, "ricerche": 1, "salvate": 2, "scartate": {"doppione": 1, "gia_valutata": 0, "link_non_verificato": 0}},
    "end_date": "2026-11-21T13:30:20.607071",
    "error_message": null,
    "id": 1,
    "llm_connection_id": 1,
    "profile_id": 1,
    "question": null,
    "search_connection_id": 2,
    "start_date": "2026-11-21T13:30:20.585881",
    "status": "COMPLETED",
    "steps": 5
  }
]
```

### Run in errore

`status: "ERROR"` e `error_message` con il motivo (testo breve, mostrabile):

```json
{
  "counters": {"pagine_lette": 0, "ricerche": 0, "salvate": 0, "scartate": {"doppione": 0, "gia_valutata": 0, "link_non_verificato": 0}},
  "end_date": "2026-11-21T13:30:20.618440",
  "error_message": "Impossibile contattare l'API Claude",
  "id": 2,
  "llm_connection_id": 1,
  "positions": [],
  "profile_id": 1,
  "question": null,
  "search_connection_id": 2,
  "start_date": "2026-11-21T13:30:20.615498",
  "status": "ERROR",
  "steps": 0
}
```

Mostra `error_message` e un pulsante "Riprova" (nuovo `POST .../runs`). Un `error_message` generico ("Errore interno durante la ricerca") significa un problema lato server. Le posizioni salvate prima dell'errore restano.

### Cosa mostra la UI

- Pagina/pannello run: stato con spinner per gli stati attivi, contatori, elenco posizioni trovate (si aggiorna col polling), pulsante "Annulla" mentre attivo.
- `WAITING_INPUT`: card ben visibile con la domanda e il form di risposta; il polling può rallentare (la ricerca è ferma finché l'utente non risponde).
- A fine run (`COMPLETED`): riepilogo "N posizioni trovate" con link alla lista da valutare (`GET /positions?run_id=<id>&stato=da_valutare`).
- Storico run per profilo (data, stato, salvate).

---

## 4. Posizioni

Le posizioni vengono dall'agente (`origine: "agente"`) o dall'inserimento manuale (`origine: "manuale"`).

### Forma della posizione

| campo | note |
|---|---|
| `id`, `user_id`, `run_id`, `profile_id` | `run_id`/`profile_id` sono `null` per le manuali o se run/profilo sono stati cancellati |
| `url`, `titolo`, `azienda`, `luogo`, `modalita`, `descrizione`, `requisiti`, `data_pubblicazione`, `fonte` | stringhe, quelle facoltative possono essere `null` |
| `punteggio_ai` | 0-100, solo per l'agente (`null` per le manuali) |
| `motivazione_ai` | perché l'agente la ritiene adatta |
| `skill_presenti`, `skill_mancanti` | liste di stringhe (`null` per le manuali) |
| `origine` | `"agente"` o `"manuale"` |
| `stato` | vedi sotto |
| `interesse` | voto dell'utente 1-5, `null` se non ancora votata |
| `motivo`, `motivo_tipo`, `motivo_preferenza` | motivo dato dall'utente nel cambio stato; `motivo_tipo` è `"generico"`, `"annuncio"` o `"preferenza"`; `motivo_preferenza` è una preferenza generale riutilizzabile ricavata dall'AI (o `null`) |
| `created_at` | ISO |

### GET /positions

Lista, più recenti prima (200). Filtri opzionali in query string, combinabili:

- `stato` (uno degli stati sotto), `origine` (`agente`/`manuale`), `profile_id`, `run_id` (interi; se non numerici `400 {"msg": "profile_id non valido"}`).

Esempio `GET /positions?run_id=1&stato=da_valutare` (una voce mostrata, l'altra ha la stessa forma):

```json
[
  {
    "azienda": "Beta Srl",
    "created_at": "2026-11-21T13:30:20.605662",
    "data_pubblicazione": null,
    "descrizione": null,
    "fonte": "jobs.example.it",
    "id": 2,
    "interesse": null,
    "luogo": "Milano",
    "modalita": "ibrido",
    "motivazione_ai": "Python e Django richiesti, ibrido a Milano",
    "motivo": null,
    "motivo_preferenza": null,
    "motivo_tipo": null,
    "origine": "agente",
    "profile_id": 1,
    "punteggio_ai": 64,
    "requisiti": null,
    "run_id": 1,
    "skill_mancanti": ["Kubernetes"],
    "skill_presenti": ["Python", "Django"],
    "stato": "da_valutare",
    "titolo": "Python Developer",
    "url": "https://jobs.example.it/annuncio/43",
    "user_id": 1
  }
]
```

La lista non contiene lo storico eventi (solo il dettaglio).

### GET /positions/<id> (dettaglio con storico)

La posizione più `eventi`, in ordine cronologico. Ogni evento è un cambio stato o un voto (nei voti `da_stato == a_stato`; nell'inserimento manuale `da_stato` è `null` e `nota` è `"inserimento manuale"`).

```json
{
  "azienda": "Acme",
  "eventi": [
    {"a_stato": "da_valutare", "created_at": "2026-11-21T13:30:20.644495", "da_stato": "da_valutare", "id": 1, "interesse": 5, "nota": null},
    {"a_stato": "promossa", "created_at": "2026-11-21T13:30:20.648000", "da_stato": "da_valutare", "id": 2, "interesse": 5, "nota": "bella"},
    {"a_stato": "candidato", "created_at": "2026-11-21T13:30:20.649614", "da_stato": "promossa", "id": 3, "interesse": 5, "nota": null}
  ],
  "id": 1,
  "interesse": 5,
  "stato": "candidato",
  "titolo": "Backend Developer",
  "...": "(tutti gli altri campi della posizione come sopra)"
}
```

`404 {"msg": "Position not found"}`. Nel dettaglio mostra: descrizione, requisiti, skill presenti/mancanti (chip verdi/rosse), punteggio e motivazione dell'AI, link all'annuncio, e la **timeline** degli eventi (data, "da_valutare -> promossa", voto, nota).

### DELETE /positions/<id>

`200 {"id": 1, "msg": "Position deleted"}` (cancella anche lo storico). `404`. Chiedi conferma.

### Votare: prima il voto, poi lo stato

**Regola: finché una posizione non ha un voto (`interesse` null) non si può cambiarne lo stato** (409). Nella UI il cambio stato deve essere disabilitato fino al voto.

`POST /positions/<id>/vote`, body `{"interesse": 5}` (intero 1-5; si può ripetere per cambiare il voto, il voto non cambia lo stato). `200` con la posizione aggiornata. `400 {"msg": "interesse deve essere un intero tra 1 e 5"}`, `404`.

### Stati e transizioni

Stati: `da_valutare`, `promossa`, `bocciata`, `non_candidato`, `candidato`, `accettato`, `rifiutato`. Le posizioni dell'agente nascono `da_valutare`.

```
da_valutare --> promossa --> candidato --> accettato
     |             |  ^          |  ^
     |             |  |          |  +----- rifiutato <--+   (accettato e rifiutato
     |             |  |          +-------------------->-+    tornano solo a candidato)
     v             |  +-- non_candidato --> candidato
  bocciata <-------+
     |
     +--> da_valutare | promossa        (da bocciata si riparte)

Da promossa si può anche tornare a da_valutare, andare a non_candidato o bocciata.
Da candidato si può tornare a promossa.
```

Il diagramma è indicativo; la tabella è la regola esatta (stato attuale -> stati raggiungibili):

| da | a |
|---|---|
| `da_valutare` | `promossa`, `bocciata` |
| `promossa` | `candidato`, `non_candidato`, `bocciata`, `da_valutare` |
| `bocciata` | `da_valutare`, `promossa` |
| `non_candidato` | `candidato`, `promossa` |
| `candidato` | `accettato`, `rifiutato`, `promossa` |
| `accettato` | `candidato` |
| `rifiutato` | `candidato` |

Mostra solo le azioni consentite per lo stato corrente. Una transizione non consentita dà `400 {"msg": "Transizione non consentita: da_valutare -> accettato"}`.

### POST /positions/<id>/status

Body:

| campo | note |
|---|---|
| `stato` | obbligatorio, nuovo stato |
| `nota` | facoltativa, finisce nello storico |
| `motivo` | **obbligatorio per `bocciata`**, facoltativo (consigliato) per gli altri cambi, es. un no a `non_candidato`/`rifiutato` |
| `conferma_generico` | `true` per inviare comunque un motivo troppo generico (vedi sotto) |

Risposta `200` con la posizione aggiornata (`stato`, `motivo`, `motivo_tipo`, `motivo_preferenza`). Esempio dopo una bocciatura con motivo riconosciuto come preferenza:

```json
{
  "azienda": "Beta Srl",
  "id": 2,
  "interesse": 1,
  "motivo": "Troppo consulenza, voglio prodotto",
  "motivo_preferenza": "evitare ruoli di consulenza",
  "motivo_tipo": "preferenza",
  "stato": "bocciata",
  "titolo": "Python Developer",
  "...": "(altri campi invariati)"
}
```

Errori, in ordine di controllo:

- `404 {"msg": "Position not found"}`
- `409 {"msg": "Prima il voto: assegna un interesse da 1 a 5"}` -> chiedi il voto.
- `400 {"msg": "Transizione non consentita: da_valutare -> accettato"}`
- `400 {"msg": "Motivo obbligatorio per la bocciatura"}` -> mostra il campo motivo.
- `400 {"msg": "motivo non valido"}` (non è una stringa)
- **`422 {"code": "motivo_generico", "msg": "Motivo troppo generico: riscrivilo o conferma"}`**: il motivo (es. "non mi piace") non spiega nulla e l'agente non può imparare da esso. La UI mostra `msg` con due azioni: "Riscrivi il motivo" (torna al campo, nessuna chiamata) oppure "Conferma così" che **reinvia la stessa richiesta con `"conferma_generico": true`**. Lo stato non è cambiato dopo il 422.

```json
{"code": "motivo_generico", "msg": "Motivo troppo generico: riscrivilo o conferma"}
```

Il motivo serve a far migliorare le ricerche successive: i motivi di tipo `preferenza` e `annuncio` vengono riassunti all'agente nelle ricerche future. Spiegalo con un breve testo di aiuto vicino al campo (es. "Un motivo concreto aiuta a trovare offerte migliori").

### Cosa mostra la UI

- Lista posizioni con filtri (stato, origine, profilo, ricerca), punteggio AI, voto a stelle (1-5), badge stato.
- Card/dettaglio: voto a stelle in evidenza; i pulsanti di stato disabilitati finché non c'è un voto; la bocciatura apre un dialog con il campo "Motivo" obbligatorio; gestione del 422 come sopra.
- Timeline eventi nel dettaglio.

---

## 5. Inserimento manuale

L'utente può aggiungere una posizione trovata da sé con un **URL** (il backend legge la pagina) o incollando il **testo** dell'annuncio. L'estrazione dei campi (titolo, azienda, luogo...) la fa l'AI: serve una connessione llm attiva.

### POST /positions/manual

| campo | note |
|---|---|
| `url` | stringa, facoltativo se c'è `testo` |
| `testo` | stringa, testo dell'annuncio; se presente non si legge la pagina (anche con `url`, che resta salvato come link) |
| `stato_iniziale` | facoltativo, default `"candidato"` (valori: gli stati sopra) |
| `interesse` | intero 1-5. **Obbligatorio se `stato_iniziale` non è `da_valutare`** (stessa regola "prima il voto") |

Serve almeno uno tra `url` e `testo`.

Esempio: `{"url": "https://gamma.example.com/jobs/7", "interesse": 4, "stato_iniziale": "promossa"}` -> `201`:

```json
{
  "azienda": "Gamma SpA",
  "created_at": "2026-11-21T13:30:20.663949",
  "data_pubblicazione": null,
  "descrizione": "Sviluppo API",
  "fonte": "gamma.example.com",
  "id": 3,
  "interesse": 4,
  "luogo": "Torino",
  "modalita": "remoto",
  "motivazione_ai": null,
  "motivo": null,
  "motivo_preferenza": null,
  "motivo_tipo": null,
  "origine": "manuale",
  "profile_id": null,
  "punteggio_ai": null,
  "requisiti": "Python, SQL",
  "run_id": null,
  "skill_mancanti": null,
  "skill_presenti": null,
  "stato": "promossa",
  "titolo": "Senior Python Engineer",
  "url": "https://gamma.example.com/jobs/7",
  "user_id": 1
}
```

### Risposte e cosa fare

| status | corpo | UI |
|---|---|---|
| `201` | la posizione creata | aggiungila alla lista / apri il dettaglio |
| `200` | la posizione **esistente** con in più `"duplicato": true` (stesso URL, ignorando parametri di tracciamento, o stessa azienda+titolo) | non è un errore: avvisa "Questa posizione c'era già" e apri quella esistente (nessuna nuova creazione) |
| `422` `{"code": "pagina_non_leggibile", "msg": "Incolla il testo dell'annuncio"}` | la pagina non si è potuta leggere (login richiesto, sito con JavaScript, URL non raggiungibile) | mostra una **textarea** per incollare il testo dell'annuncio e reinvia con `testo` (tenendo `url`, `stato_iniziale`, `interesse`) |
| `422` `{"code": "estrazione_fallita", "msg": "Non riesco a ricavare titolo e azienda: incolla il testo dell'annuncio"}` | l'AI non ha trovato titolo e azienda nel testo | stesso comportamento: textarea per un testo più completo |
| `502` `{"code": "ai_non_disponibile", "msg": "Chiave API Claude non valida"}` | il servizio AI è giu' o la chiave non funziona; `msg` dice il motivo (es. "Impossibile contattare l'API Claude", "Limite di richieste Claude superato, riprova più tardi") e varia col provider | mostra `msg` così com'è (non tradurlo dal `code`) con "Riprova"; suggerisci di provare il test connessione nelle impostazioni |
| `400 {"msg": "Serve url o testo"}` | nessuno dei due | validazione del form |
| `400 {"msg": "Nessuna connessione LLM attiva"}` | manca la connessione llm | rimanda alle impostazioni |
| `400` altri | `"Body JSON non valido"`, `"url e testo devono essere stringhe"`, `"stato_iniziale non valido"`, `"interesse deve essere un intero tra 1 e 5"` | validazione |
| `409 {"msg": "Prima il voto: assegna un interesse da 1 a 5"}` | stato iniziale diverso da `da_valutare` senza voto | rendi il voto obbligatorio nel form (o proponi `da_valutare`) |

Esempi reali:

```json
{"code": "pagina_non_leggibile", "msg": "Incolla il testo dell'annuncio"}
```

```json
{"code": "ai_non_disponibile", "msg": "Chiave API Claude non valida"}
```

Nello storico della posizione manuale compare un evento iniziale con `da_stato: null` e `nota: "inserimento manuale"`.

---

## 6. Tabella degli errori

| status | quando | cosa mostrare |
|---|---|---|
| `400` | dati non validi, transizione non consentita, motivo mancante, connessione mancante, `ENCRYPTION_KEY` assente (`"Cifratura non configurata (ENCRYPTION_KEY)"`), test connessione fallito | il `msg` (per i profili anche `errors` per campo); per le connessioni mancanti rimanda alle impostazioni |
| `401` | token mancante/scaduto | porta al login |
| `404` | risorsa inesistente o di un altro utente (`Connection not found`, `Profile not found`, `Run not found`, `Position not found`) | "Non trovato" e torna alla lista |
| `409` | ricerca già in corso; run non in attesa / già concluso; connessione in uso da una ricerca attiva; "Prima il voto" | il `msg`; ricarica lo stato del run/posizione |
| `422` | `motivo_generico` (cambio stato), `pagina_non_leggibile` e `estrazione_fallita` (inserimento manuale): hanno sempre `code` | comportamento specifico per `code` (sezioni 4 e 5), non un errore generico |
| `502` | `ai_non_disponibile` (inserimento manuale) | `msg` + "Riprova" |

Codici `code` possibili: `motivo_generico`, `pagina_non_leggibile`, `estrazione_fallita`, `ai_non_disponibile`.

---

## Da implementare nel FE

- [ ] Header `Authorization: Bearer <token>` su tutte le chiamate nuove; gestione `401`.
- [ ] **Impostazioni AI**: caricamento `/settings/providers`; lista connessioni (llm e search) con badge attiva e `••••<key_last4>`; form di creazione (kind, provider, modello solo llm, api_key); attiva/disattiva, cambia modello, sostituisci chiave (campo vuoto, mai precompilato), elimina (gestire 409 "in uso"); pulsante "Testa connessione" con esito ok/ko; messaggio dedicato per l'errore `ENCRYPTION_KEY`.
- [ ] Banner "configura le connessioni" se manca una connessione attiva llm o search.
- [ ] **Criteri di ricerca**: lista profili, form crea/modifica (ruoli, competenze con flag obbligatoria, luogo, modalità, seniority, contratto, RAL minima, lingue, esclusioni, max giorni annuncio, note), PUT come sostituzione completa, elimina con conferma; suggerimenti (`/search-profiles/suggestions`) come chip cliccabili per ruoli e competenze; errori di validazione per campo.
- [ ] **Ricerche**: pulsante "Avvia ricerca" per profilo (gestire 400 connessioni mancanti e 409 già in corso); polling di `GET /runs/<id>` ogni 2-3 s finché lo stato è attivo; indicatore di stato e contatori (ricerche, pagine, salvate, scartate per motivo); elenco posizioni trovate dal run; domanda `WAITING_INPUT` con form di risposta (`POST /runs/<id>/answer`, gestire 409); annulla (`POST /runs/<id>/cancel`, gestire 409); elimina run; `ERROR` con `error_message` e "Riprova"; storico run per profilo.
- [ ] **Posizioni**: lista con filtri (`stato`, `origine`, `profile_id`, `run_id`); card con punteggio AI, voto a stelle, badge stato; dettaglio con descrizione, requisiti, skill presenti/mancanti, motivazione AI, link e timeline `eventi`; voto 1-5 (`/vote`); cambio stato disabilitato finché manca il voto, con le sole transizioni consentite per lo stato corrente; bocciatura con motivo obbligatorio; gestione `422 motivo_generico` (riscrivi oppure reinvia con `conferma_generico: true`); elimina posizione con conferma.
- [ ] **Inserimento manuale**: form con `url` o `testo`, stato iniziale e voto (obbligatorio se non `da_valutare`); `422 pagina_non_leggibile` e `422 estrazione_fallita` -> textarea per incollare il testo e reinvio; `200` con `duplicato: true` -> avviso e apertura della posizione esistente; `502 ai_non_disponibile` -> messaggio e "Riprova"; `400` connessione LLM mancante -> rimanda alle impostazioni.
- [ ] Gestione errori per `code` (`motivo_generico`, `pagina_non_leggibile`, `estrazione_fallita`, `ai_non_disponibile`) e fallback sul `msg` per tutto il resto.
