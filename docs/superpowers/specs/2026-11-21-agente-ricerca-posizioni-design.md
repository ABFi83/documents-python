# Agente di ricerca posizioni — design

Data: 2026-11-21 · Progetto: documents-python (Flask API, `app/`)

## Intento

L'utente carica i propri CV; oggi l'app ne estrae nome, skill ed esperienze (storico per CV in `Process.result`,
somma in `GET /documents/summary`). Ora vuole che un **agente AI cerchi sul web le posizioni di lavoro migliori** per
il suo profilo, le salvi, e che lui possa valutarle, seguirne il percorso (candidatura, esito) e che **ogni ricerca
successiva impari dalle valutazioni precedenti**. Vuole un processo dinamico (l'agente decide cosa cercare, legge le
pagine, approfondisce, gli fa domande se ha dubbi), non una pipeline di query fisse. L'AI deve essere intercambiabile
(Claude, ChatGPT, Gemini, …): si sceglie da una sezione di impostazioni e se ne possono aggiungere altre.

Il FE è un progetto separato; questo documento copre il BE. Alla fine dell'implementazione si genera un brief per il
Claude del FE (come fatto per lo storico CV).

## Obiettivi

1. Impostazioni AI: connessioni salvate dall'utente (provider, modello, chiave API cifrata nel DB), una attiva per tipo.
2. Ruolo obiettivo estratto da ogni CV (oltre ai ruoli delle esperienze), usato come suggerimento.
3. Criteri di ricerca salvati, in parte suggeriti dai CV.
4. Esecuzione di ricerca con un agente: cerca, legge, salva posizioni, può fare domande all'utente e attendere la risposta.
5. Controlli nel codice: link verificati, doppioni, posizioni già valutate.
6. Valutazione: interesse 1–5 + esito + motivo; ciclo di vita della posizione con storico completo.
7. I voti e gli stati influenzano le ricerche successive, pesati.
8. Inserimento manuale di una candidatura da link (o testo incollato), con estrazione dei dati.

## Non obiettivi (per ora)

- Ricerche periodiche automatiche (solo avvio a richiesta).
- Adattatori per più AI subito: si implementa **un** adattatore LLM (Claude) e **un** provider di ricerca; gli altri
  si aggiungono uno alla volta, ciascuno col suo codice.
- Invio candidature, email, calendario colloqui.
- Lettura di siti che richiedono login (LinkedIn): non si aggira, si chiede il testo all'utente.

## Anti-obiettivi (sarebbe un fallimento anche se "funziona")

- Mostrare all'utente una posizione con un link mai visto dall'agente (link inventato).
- Riproporre una posizione già valutata, o la stessa posizione due volte (anche da siti diversi).
- Mandare all'AI o al provider di ricerca dati personali di contatto del CV: nome, cognome, email, telefono, link a
  profili. (I nomi delle aziende delle esperienze invece si mandano: decisione dell'utente.)
- Far trapelare le chiavi API: al FE, nei log, nelle risposte d'errore. **Attenzione**: `app/__init__.py` logga il
  body di ogni richiesta (`log_request_info`); va oscurato per le richieste che contengono chiavi.

## Vincoli

- Stack esistente: Flask 3, Flask-SQLAlchemy, SQLite in `instance/db.sqlite`, Marshmallow, JWT (`get_jwt_identity()`
  è stringa → `int()`), thread in background per i lavori lunghi (pattern di `analyze_file` + `Process`).
- **Niente migrazioni**: tabelle nuove le crea `db.create_all()`; colonne nuove su tabelle esistenti vanno aggiunte a
  mano (`ALTER TABLE`) sul DB locale, come fatto per `process.document_id`.
- Scritture dai thread che possono "perdere la corsa" con una cancellazione: stesso schema di `save_process`
  (UPDATE condizionato per primo nella transazione, `rowcount == 0` → rollback, niente scritto).
- Test con `create_app({...})` e SQLite in memoria; chiamate AI e ricerca sempre mockate nei test.
- Python 3.14, venv `.venv`.

## Approcci considerati

| | Approccio | Pro | Contro |
|---|---|---|---|
| A | Ricerca web nativa di ogni AI (Claude `web_search`, OpenAI web search, Gemini grounding) | Agente vero, nessun servizio di ricerca esterno | Integrazione diversa per provider, qualità variabile, controllo link diverso per provider, AI senza ricerca web non usabili |
| **B** | **Agente con nostri strumenti** (`cerca_web`, `leggi_pagina`, `salva_posizione`, `fai_domanda`) su un'API di ricerca nostra | Comportamento uguale per tutte le AI, link verificabili perché li produciamo noi, l'agente può fare domande | Ogni AI richiede il suo adattatore di function calling; serve una chiave in più per l'API di ricerca |
| C | Pipeline a passi fissi (query generate → ricerca → scoring) | Adattatore minimo, costi prevedibili | Poco dinamica, nessuna domanda all'utente |

**Scelto: B** (decisione dell'utente): vuole un agente dinamico che possa fare domande; accetta di scrivere codice
per ogni AI. A resta possibile in futuro come fonte di ricerca alternativa.

## Design

### 1. Connessioni (impostazioni AI)

Tabella `AiConnection`: `id`, `user_id`, `kind` (`llm` | `search`), `provider` (es. `claude`, `openai`, `gemini`,
`brave`…), `model` (solo `llm`), `api_key_enc` (cifrata), `key_last4`, `active` (bool), `created_at`.

- **Per utente** (mia scelta: l'app è già multi-utente e ogni dato è per utente).
- Al più una connessione `active` per `(user_id, kind)`; attivarne una disattiva le altre dello stesso tipo.
- Cifratura: Fernet (`cryptography`), chiave master in variabile d'ambiente `ENCRYPTION_KEY` (mai nel DB, mai nel
  repo). Senza `ENCRYPTION_KEY` il salvataggio di una chiave restituisce errore chiaro.
- API: CRUD su `/settings/connections`; la chiave non viene mai restituita (solo `key_last4`); la chiave si può
  sostituire, non leggere. `POST /settings/connections/<id>/test` fa una chiamata minima al provider e risponde
  ok/errore (messaggio d'errore ripulito, senza chiave).
- `GET /settings/providers`: elenco dei provider supportati dal codice (per `kind`), con i modelli suggeriti; il FE
  propone solo quelli.
- Le richieste a queste rotte non devono finire in chiaro nel log del body.

### 2. Ruolo obiettivo del CV

`extract_service` aggiunge `ruolo_obiettivo` a `Process.result`: la riga di titolo vicino al nome (nel CV di prova:
"Senior Python Engineer · Backend, Microservizi & Sistemi Distribuiti" → "Senior Python Engineer"). Se non trovato,
`null`. I CV già estratti non hanno il campo: va gestito come assente.

### 3. Criteri di ricerca

Tabella `SearchProfile` (un insieme di criteri con nome, es. "Backend Python remoto"): `ruoli` (lista),
`competenze` (lista di `{nome, obbligatoria}`), `luogo`, `modalita` (lista tra `remoto`, `ibrido`, `presenza`),
`seniority`, `contratto`, `ral_min`, `lingue`, `esclusioni` (aziende/settori, testo libero in lista),
`max_giorni_annuncio` (default 30), `note` (testo libero per l'agente). Campi strutturati in colonne o JSON a scelta
del builder.

- CRUD su `/search-profiles`.
- `GET /search-profiles/suggestions`: dai CV `COMPLETED` dell'utente → ruoli obiettivo, ruoli delle esperienze più
  recenti, competenze della somma (ordinate per numero di CV). Il FE li propone, l'utente sceglie.

### 4. Esecuzione di una ricerca (l'agente)

Tabella `SearchRun`: `profile_id`, `user_id`, `connection_id` LLM e di ricerca usate, `status`
(`PENDING`, `RUNNING`, `WAITING_INPUT`, `COMPLETED`, `ERROR`, `CANCELLED`), `question` (domanda in attesa),
`messages` (conversazione nel formato nativo del provider, JSON, per riprendere dopo una risposta), contatori
(`ricerche`, `pagine_lette`, `salvate`, `scartate` per motivo: `link_non_verificato`, `doppione`, `gia_valutata`),
`error_message`, `start_date`, `end_date`.

- `POST /search-profiles/<id>/runs` → 202 con il run; parte un thread. Richiede una connessione `llm` e una `search`
  attive (altrimenti 400 con messaggio chiaro).
- Strumenti dell'agente (definiti una volta, tradotti da ogni adattatore nel formato del suo provider):
  - `cerca_web(query, max_risultati)` → `[{url, titolo, snippet}]` dal provider di ricerca attivo;
  - `leggi_pagina(url)` → testo della pagina (o errore "non leggibile");
  - `salva_posizione({...dati...})` → esito dei controlli (§5), che torna all'agente perché possa correggersi;
  - `fai_domanda(testo)` → mette il run in `WAITING_INPUT` con `question`, salva `messages`, il thread termina.
- `POST /runs/<id>/answer {testo}` (solo in `WAITING_INPUT`) → aggiunge la risposta alla conversazione e riparte un
  thread dallo stato salvato. Una sola domanda in attesa per volta. Nessun timeout: il run aspetta finché l'utente
  risponde o annulla.
- `POST /runs/<id>/cancel` → `CANCELLED`; il thread in corso se ne accorge alla prossima scrittura (schema
  `save_process`) e non scrive altro.
- `GET /search-profiles/<id>/runs`, `GET /runs/<id>`: stato, domanda, contatori, posizioni salvate dal run.
- Limiti per run (valori al builder, configurabili): passi massimi del loop, ricerche massime, pagine lette massime,
  posizioni salvate massime. Al raggiungimento l'agente viene invitato a chiudere; oltre, il run chiude `COMPLETED`.
- Contesto dato all'agente: i criteri del profilo, il profilo professionale dai CV **senza dati personali di contatto**
  (ruoli, skill, anni di esperienza, settori **e nomi delle aziende** delle esperienze: decisione dell'utente, danno
  contesto all'agente), il riassunto delle valutazioni (§7), l'elenco delle aziende/URL già visti (o un modo
  compatto per escluderli). Note dei criteri e risposte dell'utente alle domande passano come scritte.
  Test: nessun nome, cognome, email, telefono o link a profili arriva all'adattatore mockato.

### 5. Controlli nel codice (su `salva_posizione`)

1. **Link verificato**: l'URL (normalizzato) deve essere comparso in un risultato di `cerca_web` o essere stato letto
   con `leggi_pagina` **in questo run**. Altrimenti rifiuto (`link_non_verificato`).
2. **Normalizzazione URL**: host minuscolo, niente frammento, niente parametri di tracciamento (`utm_*`, `gclid`,
   `fbclid`, `ref`, …), niente `/` finale.
3. **Doppioni**: stesso URL normalizzato, oppure stessa azienda + stesso titolo normalizzati, tra **tutte** le
   posizioni dell'utente → rifiuto (`doppione`). Se la posizione esistente è già valutata → `gia_valutata`.
4. Campi obbligatori minimi: titolo, azienda, URL. Il resto facoltativo.
Ogni rifiuto incrementa il contatore del run e torna all'agente come risposta dello strumento.

### 6. Posizioni, valutazione, ciclo di vita

Tabella `Position`: `user_id`, `run_id` (null se manuale), `profile_id` (null se manuale), `url`, `url_norm`,
`titolo`, `azienda`, `luogo`, `modalita`, `descrizione`, `requisiti`, `data_pubblicazione`, `fonte`,
`punteggio_ai` (0–100), `motivazione_ai`, `skill_presenti`, `skill_mancanti`, `origine` (`agente` | `manuale`),
`stato`, `interesse` (1–5, null finché non votata), `motivo`, `motivo_tipo` (`generico` | `annuncio` | `preferenza`),
`motivo_preferenza` (testo normalizzato della preferenza, se `preferenza`), `created_at`.

Tabella `PositionEvent` (storico): `position_id`, `da_stato`, `a_stato`, `interesse`, `nota`, `created_at`. Ogni
cambio di stato e ogni voto crea un evento.

Stati e transizioni (decisi dall'utente):

```
da_valutare ──► promossa ──► candidato ──► accettato
     │             │               └─────► rifiutato   (dall'azienda)
     │             └──► non_candidato    (valida ma non interessa)
     └──► bocciata  (motivo obbligatorio)
```

- **Prima il voto, poi lo stato**: non si esce da `da_valutare` senza `interesse`. Il voto si può cambiare sempre.
- Indietro di un passo consentito (es. `bocciata` → `da_valutare`/`promossa`), sempre registrato nello storico.
- Bocciatura: `motivo` obbligatorio. Promozione: motivo facoltativo.
- **Controllo del motivo** al salvataggio: l'AI attiva classifica il motivo in `generico` / `annuncio` (riguarda solo
  quella posizione o azienda) / `preferenza` (es. "troppo manageriale" → preferenza "evitare ruoli manageriali").
  Se `generico` la rotta risponde con un avviso e il FE chiede di riscriverlo; se l'utente conferma (flag
  `conferma_generico`), si salva con `motivo_tipo = generico`. Senza connessione AI attiva: regola minima
  (lunghezza/parole) a scelta del builder.
- API: `GET /positions` (filtri: stato, profilo, run, origine; ordinamento), `GET /positions/<id>` (con storico),
  `POST /positions/<id>/vote {interesse, motivo?}`, `POST /positions/<id>/status {stato, nota?, motivo?,
  conferma_generico?}`, `DELETE /positions/<id>`.

### 7. Come le valutazioni guidano le ricerche successive

Prima di ogni run il codice costruisce un riassunto per l'agente:
- **Esempi positivi**: posizioni con interesse 4–5, `candidato`, `accettato` (questi ultimi due più forti di
  interesse 5).
- **Esempi negativi**: interesse 1–2; `non_candidato` con interesse basso (segnale debole).
- **Preferenze da evitare**: motivi `preferenza`; peso pieno se espressi nello stesso profilo, più leggero negli altri;
  più forte se la stessa preferenza ricorre.
- **Non usati come preferenze**: motivi `generico`, motivi `annuncio` (valgono solo per escludere quella posizione o
  azienda se il motivo lo dice), esito `rifiutato` dell'azienda (serve solo a non riproporre).
- Tutte le posizioni già esistenti non vengono riproposte (§5).
Numeri dei pesi, quanti esempi passare e il formato del riassunto: al builder, purché rispettino queste regole.

### 8. Inserimento manuale

`POST /positions/manual {url? , testo?, stato_iniziale? (default candidato), interesse?}`:
- Con `url`: il BE legge la pagina (stesso codice di `leggi_pagina`) ed estrae i campi con una chiamata all'AI attiva
  (output JSON). Se la pagina non è leggibile → 422 con messaggio "incolla il testo dell'annuncio".
- Con `testo` (e opzionalmente `url`): estrazione dal testo.
- Stessi controlli di doppione (se esiste già, restituisce quella esistente con un avviso). `origine = manuale`.
- Se lo stato iniziale non è `da_valutare`, serve `interesse` (regola "prima il voto").

### 9. Adattatori

- **LLM**: un'interfaccia comune, un'implementazione per provider, nel formato nativo del provider:
  - un passo del loop: conversazione + definizione strumenti → testo e/o chiamate a strumenti;
  - aggiunta dei risultati degli strumenti e della risposta dell'utente alla conversazione;
  - `estrai_json(prompt, schema)` per classificazione motivi ed estrazione manuale;
  - `test()` per la verifica della connessione.
  Prima implementazione: **Claude** con l'SDK ufficiale `anthropic`, modello predefinito `claude-opus-5-5`.
- **Ricerca**: interfaccia `cerca(query, n) → [{url, titolo, snippet}]` + `test()`. Una prima implementazione; quale
  API (es. Brave Search, Tavily) la sceglie il builder dopo una prova su query di annunci italiani.
- Aggiungere un'AI = nuovo adattatore + voce in `GET /settings/providers`. Nessuna libreria che unifica i provider
  (decisione dell'utente).

## Cancellazioni e reset (mia scelta)

- `POST /users/reset` (usato solo per i test, dice l'utente) resta com'è (CV, estrazioni, skill, esperienze):
  **non** tocca posizioni, criteri, run e connessioni.
- Cancellare un profilo o un run **non** cancella le posizioni: `profile_id` / `run_id` diventano `null`
  (le valutazioni restano e continuano a guidare le ricerche). Cancellare un profilo con un run attivo lo annulla prima.
- Cancellare una connessione in uso da un run attivo: rifiutato (409) finché il run non finisce o viene annullato.

## Sicurezza di `leggi_pagina` (mia scelta)

- Solo `http`/`https`; niente host che risolvono su IP privati, loopback o link-local (evita che l'agente o un link
  manuale facciano leggere al server risorse interne); limite di dimensione e timeout.

## Concorrenza (mia scelta)

- Un solo run attivo (`PENDING`/`RUNNING`/`WAITING_INPUT`) per utente: un secondo avvio risponde 409.

## Lasciato al builder

- Nomi esatti di tabelle/colonne, colonne vs JSON per i campi dei criteri.
- Quale API di ricerca per prima (dopo una prova), e come estrarre il testo dalle pagine HTML.
- Testo dei prompt, valori dei limiti per run, pesi numerici del riassunto (§7).
- Struttura dei file (`app/services/agent/…`, `app/routes/…`), purché segua i pattern esistenti.
- Brief per il Claude del FE a fine lavoro.
