import unittest
from app import create_app, db

class AuthTestCase(unittest.TestCase):
    def setUp(self):
        """Configura l'applicazione per i test."""
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})  # Database in memoria
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        """Elimina il database dopo ogni test."""
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_register(self):
        """Testa la registrazione di un nuovo utente."""
        response = self.client.post('/auth/register', json={
            'username': 'testuser',
            'password': 'testpassword'
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('testuser', response.get_json()['username'])

    def test_login_success(self):
        """Testa il login con credenziali valide."""
        # Registra un utente
        self.client.post('/auth/register', json={
            'username': 'testuser',
            'password': 'testpassword'
        })

        # Effettua il login
        response = self.client.post('/auth/login', json={
            'username': 'testuser',
            'password': 'testpassword'
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('access_token', response.get_json())

    def test_login_failure(self):
        """Testa il login con credenziali non valide."""
        # Registra un utente
        self.client.post('/auth/register', json={
            'username': 'testuser',
            'password': 'testpassword'
        })

        # Effettua il login con una password errata
        response = self.client.post('/auth/login', json={
            'username': 'testuser',
            'password': 'wrongpassword'
        })
        self.assertEqual(response.status_code, 401)
        self.assertIn('msg', response.get_json())
        self.assertEqual(response.get_json()['msg'], 'Bad credentials')

if __name__ == '__main__':
    unittest.main()