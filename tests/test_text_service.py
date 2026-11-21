import io
import unittest
from unittest.mock import MagicMock, patch

import PyPDF2
import requests

from app.services.text_service import pdf_to_text


def blank_pdf() -> bytes:
    writer = PyPDF2.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class TextServiceTestCase(unittest.TestCase):
    @patch('app.services.text_service.requests.post')
    def test_uses_docling_text(self, post):
        post.return_value = MagicMock(json=lambda: {
            'status': 'success',
            'document': {'text_content': 'COMPETENZE TECNICHE\nPython'},
        })
        text = pdf_to_text('http://docling:5001/', 'cv.pdf', b'%PDF')
        self.assertEqual(text, 'COMPETENZE TECNICHE\nPython')
        args, kwargs = post.call_args
        self.assertEqual(args[0], 'http://docling:5001/v1/convert/file')
        self.assertEqual(kwargs['data']['to_formats'], 'text')

    @patch('app.services.text_service.requests.post', side_effect=requests.ConnectionError('down'))
    def test_falls_back_to_pypdf2_when_docling_down(self, _post):
        self.assertEqual(pdf_to_text('http://docling:5001', 'cv.pdf', blank_pdf()), '')

    @patch('app.services.text_service.requests.post')
    def test_falls_back_when_conversion_fails(self, post):
        post.return_value = MagicMock(json=lambda: {'status': 'failure', 'errors': ['boom']})
        self.assertEqual(pdf_to_text('http://docling:5001', 'cv.pdf', blank_pdf()), '')


if __name__ == '__main__':
    unittest.main()
