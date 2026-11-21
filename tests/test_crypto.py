import unittest
from cryptography.fernet import Fernet
from app import create_app
from app.utils.crypto import encrypt, decrypt, CryptoNotConfigured


def make_app(**extra):
    cfg = {'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'}
    cfg.update(extra)
    return create_app(cfg)


class CryptoTestCase(unittest.TestCase):
    def test_round_trip(self):
        app = make_app(ENCRYPTION_KEY=Fernet.generate_key().decode())
        with app.app_context():
            token = encrypt('sk-abc')
            self.assertNotIn('sk-abc', token)
            self.assertEqual(decrypt(token), 'sk-abc')

    def test_senza_chiave(self):
        app = make_app(ENCRYPTION_KEY=None)
        with app.app_context():
            with self.assertRaises(CryptoNotConfigured):
                encrypt('sk-abc')


class LogRedactionTestCase(unittest.TestCase):
    def test_body_settings_non_loggato(self):
        client = make_app().test_client()
        with self.assertLogs(level='INFO') as cm:
            client.post('/settings/x', data='sk-segreto-123')
            client.post('/nonexistent', data='corpo-visibile')
        out = '\n'.join(cm.output)
        self.assertNotIn('sk-segreto-123', out)
        self.assertIn('corpo-visibile', out)


if __name__ == '__main__':
    unittest.main()
