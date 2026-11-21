import unittest
from unittest.mock import patch, MagicMock

from app.services.agent.pages import read_page, PageError


def addr(ip):
    return [(2, 1, 6, '', (ip, 0))]


def resp(status=200, body=b'', ctype='text/html; charset=utf-8', location=None, encoding='utf-8'):
    r = MagicMock()
    r.status_code = status
    r.headers = {'Content-Type': ctype}
    if location:
        r.headers['Location'] = location
    r.encoding = encoding
    r.iter_content.side_effect = lambda chunk_size=8192: iter([body[i:i + chunk_size] for i in range(0, len(body), chunk_size)])
    return r


class PagesTestCase(unittest.TestCase):
    def run_read(self, url, responses, ip='93.184.216.34', **kw):
        with patch('socket.getaddrinfo', return_value=addr(ip)), \
             patch('requests.get', side_effect=responses) as g:
            return read_page(url, **kw), g

    def test_literal_private_hosts(self):
        for u in ('http://127.0.0.1/', 'http://10.0.0.5/', 'http://[::1]/', 'http://[::ffff:127.0.0.1]/'):
            with patch('requests.get') as g:
                with self.assertRaises(PageError):
                    read_page(u)
                g.assert_not_called()

    def test_hostname_resolving_private(self):
        with patch('socket.getaddrinfo', return_value=addr('192.168.1.1') + addr('93.184.216.34')), \
             patch('requests.get') as g:
            with self.assertRaises(PageError):
                read_page('http://example.com/')
            g.assert_not_called()

    def test_backslash_parser_differential(self):
        def gai(host, *a, **k):
            return addr(host) if host[0].isdigit() else addr('93.184.216.34')
        with patch('socket.getaddrinfo', side_effect=gai), patch('requests.get') as g:
            with self.assertRaises(PageError):
                read_page('http://127.0.0.1\@example.com/')
            g.assert_not_called()

    def test_cgnat_blocked(self):
        with patch('requests.get') as g:
            with self.assertRaises(PageError):
                read_page('http://100.100.100.200/latest/meta-data')
            g.assert_not_called()

    def test_body_read_error(self):
        import requests
        r = resp(body=b'x')
        r.iter_content.side_effect = requests.exceptions.ChunkedEncodingError()
        with self.assertRaises(PageError):
            self.run_read('https://example.com/', [r])

    def test_bogus_charset(self):
        out, _ = self.run_read('https://example.com/', [resp(body=b'<p>ok</p>', ctype='text/html; charset=bogus')])
        self.assertEqual(out, 'ok')

    def test_idna_charset(self):
        out, _ = self.run_read('https://example.com/', [resp(body='<p>caffè</p>'.encode(), ctype='text/html; charset=idna')])
        self.assertEqual(out, 'caffè')

    def test_no_charset_defaults_utf8(self):
        out, _ = self.run_read('https://example.com/', [resp(body='<p>perché città</p>'.encode(), ctype='text/html', encoding='ISO-8859-1')])
        self.assertEqual(out, 'perché città')

    def test_bad_scheme(self):
        with self.assertRaises(PageError):
            read_page('ftp://x')

    def test_redirect_to_metadata_blocked(self):
        def gai(host, *a, **k):
            return addr(host) if host[0].isdigit() else addr('93.184.216.34')
        with patch('socket.getaddrinfo', side_effect=gai), \
             patch('requests.get', side_effect=[resp(302, location='http://169.254.169.254/')]) as g:
            with self.assertRaises(PageError):
                read_page('http://example.com/')
            self.assertEqual(g.call_count, 1)

    def test_relative_redirect_followed_and_too_many(self):
        out, g = self.run_read('http://example.com/a', [resp(302, location='/b'), resp(body=b'<p>ok</p>')])
        self.assertEqual(out, 'ok')
        self.assertEqual(g.call_args.args[0], 'http://example.com/b')
        self.assertFalse(g.call_args.kwargs['allow_redirects'])
        with self.assertRaises(PageError):
            self.run_read('http://example.com/a', [resp(302, location='/b')] * 5)

    def test_html_to_text(self):
        html = b'<html><head><style>x{}</style></head><body><script>evil()</script><noscript>n</noscript><h1>Ciao</h1>\n\n<p>  mondo   </p></body></html>'
        out, _ = self.run_read('https://example.com/', [resp(body=html)])
        self.assertEqual(out, 'Ciao mondo')

    def test_truncate_and_plain_text(self):
        out, _ = self.run_read('https://example.com/', [resp(body=b'a' * 100, ctype='text/plain')], max_chars=10)
        self.assertEqual(out, 'a' * 10)

    def test_http_error(self):
        with self.assertRaises(PageError) as c:
            self.run_read('https://example.com/', [resp(403)])
        self.assertIn('403', str(c.exception))

    def test_unsupported_type(self):
        with self.assertRaises(PageError):
            self.run_read('https://example.com/', [resp(body=b'%PDF', ctype='application/pdf')])

    def test_size_limit_stops_stream(self):
        out, _ = self.run_read('https://example.com/', [resp(body=b'a' * (3 * 1024 * 1024), ctype='text/plain')], max_chars=10**9)
        self.assertEqual(len(out), 2 * 1024 * 1024)


if __name__ == '__main__':
    unittest.main()
