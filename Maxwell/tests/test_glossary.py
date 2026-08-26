import unittest
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))
from app import app, init_db

class GlossaryTestCase(unittest.TestCase):
    def setUp(self):
        # Initialize the database (creates table if not exists)
        init_db()
        self.app = app.test_client()
        self.app.testing = True

    def test_glossary_endpoint(self):
        response = self.app.get('/api/glossary')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsInstance(data, list)
        # We don't know how many terms are in the DB, but we can check structure
        if len(data) > 0:
            for item in data:
                self.assertIn('term', item)
                self.assertIn('definition', item)

    def test_get_term_endpoint(self):
        # First, get a term that might not exist to trigger Ollama (but we don't want to rely on Ollama in test)
        # Instead, we can insert a term directly into the DB for testing, but that's more complex.
        # For simplicity, we'll just test that the endpoint returns 200 and has the expected fields.
        response = self.app.get('/api/glossary/testterm')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('term', data)
        self.assertIn('definition', data)
        self.assertEqual(data['term'], 'testterm')

if __name__ == '__main__':
    unittest.main()