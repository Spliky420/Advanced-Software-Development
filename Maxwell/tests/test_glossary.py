import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

# A throwaway database for the whole session. app.py reads DATABASE at import
# time and creates the file if it is missing, so setting this before `app` is
# imported keeps the suite off the repository's Maxwell/database/glossary.sqlite
# and gives every run the empty starting state a fresh clone has.
_TEST_DB = os.path.join(tempfile.mkdtemp(prefix='maxwell-glossary-test-'), 'glossary.sqlite')

# The suite must not depend on a running Ollama, so the definition returned for
# a generated term comes from a mocked response rather than a real model call
# (the same approach joshua/ and Enerel/ take in their tests).
_MOCK_DEFINITION = 'A definition supplied by the mocked model.'


class GlossaryTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Set the environment the app reads at import time. AI mode is forced
        # ON so the generation path is exercised, but it talks to the mock
        # below, not to Ollama -- so the suite stays hermetic even though CI
        # sets DISABLE_AI_MODE.
        os.environ['DATABASE'] = _TEST_DB
        os.environ['DISABLE_AI_MODE'] = 'false'
        os.environ['OLLAMA_BASE_URL'] = 'http://localhost:11434'
        os.environ['OLLAMA_MODEL'] = 'qwen2.5:0.5b'

        from app import app
        cls.app = app

    def setUp(self):
        from app import init_db
        init_db()
        self.client = self.app.test_client()
        self.client.testing = True

    def test_glossary_endpoint(self):
        response = self.client.get('/api/glossary')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsInstance(data, list)
        for item in data:
            self.assertIn('term', item)
            self.assertIn('definition', item)

    def test_get_term_endpoint(self):
        # The term is not in the (empty) test database, so the endpoint takes
        # its generation path. requests.post is mocked, so the request needs no
        # Ollama and returns 200 instead of the 503 a disabled/unreachable
        # generation path would produce.
        with mock.patch('app.requests.post') as mocked_post:
            mocked_post.return_value.json.return_value = {'response': _MOCK_DEFINITION}
            response = self.client.get('/api/glossary/testterm')

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('term', data)
        self.assertIn('definition', data)
        self.assertEqual(data['term'], 'testterm')
        self.assertEqual(data['definition'], _MOCK_DEFINITION)


if __name__ == '__main__':
    unittest.main()
