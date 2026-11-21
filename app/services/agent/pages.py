"""Lettura sicura di pagine web (confine SSRF: URL scelti da AI e utente)."""
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests
from urllib3.util import parse_url

MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECT = 3
TIMEOUT = 15


class PageError(Exception):
    """Messaggio breve in italiano, sicuro da mostrare ad agente/utente."""


def _ip_vietato(ip):
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    # not is_global copre anche 100.64.0.0/10 (CGNAT, metadata cloud)
    return (not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def _prepara_url(url):
    """URL normalizzato come lo invierebbe requests; host validato con lo stesso parser (urllib3)."""
    try:
        url = requests.Request('GET', url).prepare().url
        p = parse_url(url)
    except Exception:
        raise PageError('URL non valido')
    host = (p.host or '').strip('[]')
    if p.scheme not in ('http', 'https') or not host:
        raise PageError('URL non valido: sono ammessi solo http e https')
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == 'https' else 80),
                                   proto=socket.IPPROTO_TCP)
        ips = [ipaddress.ip_address(i[4][0].split('%')[0]) for i in infos]
    except (OSError, ValueError):
        raise PageError('Host non raggiungibile')
    if not ips or any(_ip_vietato(ip) for ip in ips):
        raise PageError('Indirizzo non consentito')
    return url


class _Testo(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parti, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript') and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parti.append(data)


def read_page(url: str, max_chars: int = 20000) -> str:
    for _ in range(MAX_REDIRECT + 1):
        url = _prepara_url(url)
        # ponytail: DNS rebinding tra controllo e risoluzione di requests non prevenuto
        try:
            r = requests.get(url, timeout=TIMEOUT, stream=True, allow_redirects=False,
                             headers={'User-Agent': 'Mozilla/5.0 (CV-agent)'})
        except requests.RequestException:
            raise PageError('Pagina non raggiungibile')
        try:
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get('Location'):
                url = urljoin(url, r.headers['Location'])
                continue
            if r.status_code >= 400:
                raise PageError(f'Pagina non leggibile (HTTP {r.status_code})')
            ctype = r.headers.get('Content-Type', '').split(';')[0].strip().lower()
            if ctype not in ('text/html', 'application/xhtml+xml') and not ctype.startswith('text/'):
                raise PageError('Contenuto non supportato')
            buf = b''
            try:
                for chunk in r.iter_content(chunk_size=8192):
                    buf += chunk
                    if len(buf) >= MAX_BYTES:
                        buf = buf[:MAX_BYTES]
                        break
            except requests.RequestException:
                raise PageError('Pagina non raggiungibile')
        finally:
            r.close()
        # charset dall'header (assente -> utf-8, non il default ISO-8859-1 di requests)
        charset = 'utf-8'
        for par in r.headers.get('Content-Type', '').split(';')[1:]:
            k, _, v = par.partition('=')
            if k.strip().lower() == 'charset' and v.strip():
                charset = v.strip().strip('"\'')
        try:
            testo = buf.decode(charset, errors='replace')
        except (LookupError, UnicodeError):
            testo = buf.decode('utf-8', errors='replace')
        if ctype != 'text/plain':
            p = _Testo()
            p.feed(testo)
            testo = ' '.join(p.parti)
        return ' '.join(testo.split())[:max_chars]
    raise PageError('Troppi reindirizzamenti')
