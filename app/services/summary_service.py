def _unisci_nomi(estrazioni, chiave):
    """[{nome, document_ids}] senza doppioni (case-insensitive), i più presenti prima."""
    voci = {}
    for doc_id, result in estrazioni:
        for nome in result.get(chiave) or []:
            voce = voci.setdefault(nome.casefold(), {"nome": nome, "document_ids": []})
            if doc_id not in voce["document_ids"]:
                voce["document_ids"].append(doc_id)
    return sorted(voci.values(), key=lambda v: (-len(v["document_ids"]), v["nome"].casefold()))


def somma_estrazioni(estrazioni):
    """
    Somma delle estrazioni di più CV. `estrazioni`: [(document_id, result)], dal CV più recente.
    Un'esperienza è la stessa se coincidono azienda, ruolo (case-insensitive) e data di inizio:
    restano i dati del CV più recente, `document_ids` dice in quali CV compare.
    """
    esperienze = {}
    for doc_id, result in estrazioni:
        for e in result.get("esperienze") or []:
            chiave = ((e.get("azienda") or "").strip().casefold(),
                      (e.get("ruolo") or "").strip().casefold(),
                      e.get("start_date"))
            voce = esperienze.setdefault(chiave, {**e, "document_ids": []})
            if doc_id not in voce["document_ids"]:
                voce["document_ids"].append(doc_id)
    return {
        "documenti": len(estrazioni),
        "linguaggi": _unisci_nomi(estrazioni, "linguaggi"),
        "frameworks": _unisci_nomi(estrazioni, "frameworks"),
        # più recenti prima, senza data in fondo (le date ISO si ordinano come stringhe)
        "esperienze": sorted(esperienze.values(), key=lambda e: e.get("start_date") or "", reverse=True),
    }
