import io
import logging

import PyPDF2
import requests


def docling_to_text(url: str, filename: str, data: bytes) -> str:
    """Converte il file con docling-serve (POST /v1/convert/file, sincrono)."""
    r = requests.post(
        f"{url.rstrip('/')}/v1/convert/file",
        files={"files": (filename, data, "application/pdf")},
        # "text" e non "md": niente '#'/'-' che romperebbero le regex di extract_service
        data={"to_formats": "text", "do_ocr": "true"},
        timeout=300,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("status") not in ("success", "partial_success"):
        raise RuntimeError(f"Docling: conversione {body.get('status')}: {body.get('errors')}")
    return body["document"]["text_content"]


def pdf_to_text(docling_url: str, filename: str, data: bytes) -> str:
    """Testo del PDF da Docling; se Docling non risponde o fallisce, PyPDF2 (senza OCR)."""
    try:
        return docling_to_text(docling_url, filename, data)
    except Exception as e:
        logging.warning(f"Docling non disponibile ({e}), uso PyPDF2")
    reader = PyPDF2.PdfReader(io.BytesIO(data))
    return "".join(page.extract_text() or "" for page in reader.pages)
