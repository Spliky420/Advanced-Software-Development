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
        """Test GET /api/glossary - list all terms"""
        response = self.client.get('/api/glossary')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsInstance(data, list)
        for item in data:
            self.assertIn('term', item)
            self.assertIn('definition', item)

    def test_get_term_endpoint(self):
        """Test GET /api/glossary/<term> - generate definition for missing term"""
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

    # --- Post-commit CI/CD endpoint tests ---

    def test_create_term_endpoint(self):
        """Test POST /api/glossary/<term> - create new term with AI generation"""
        # This tests the endpoint that creates a term (calls GET which generates if missing)
        with mock.patch('app.requests.post') as mocked_post:
            mocked_post.return_value.json.return_value = {'response': _MOCK_DEFINITION}
            response = self.client.get('/api/glossary/newterm')

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['term'], 'newterm')
        self.assertEqual(data['definition'], _MOCK_DEFINITION)

        # Verify it's now in the database
        response2 = self.client.get('/api/glossary')
        data2 = response2.get_json()
        terms = [item['term'] for item in data2]
        self.assertIn('newterm', terms)

    def test_update_term_endpoint(self):
        """Test PUT /api/glossary/<term> - update existing term definition"""
        # First create a term
        with mock.patch('app.requests.post') as mocked_post:
            mocked_post.return_value.json.return_value = {'response': _MOCK_DEFINITION}
            self.client.get('/api/glossary/updateterm')

        # Now update it
        new_def = 'Updated definition for testing'
        response = self.client.put('/api/glossary/updateterm',
                                   json={'definition': new_def},
                                   content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['term'], 'updateterm')
        self.assertEqual(data['definition'], new_def)

    def test_update_nonexistent_term(self):
        """Test PUT /api/glossary/<term> - 404 for non-existent term"""
        response = self.client.put('/api/glossary/nonexistent',
                                   json={'definition': 'test'},
                                   content_type='application/json')
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertIn('error', data)

    def test_update_term_empty_definition(self):
        """Test PUT /api/glossary/<term> - 400 for empty definition"""
        # First create a term
        with mock.patch('app.requests.post') as mocked_post:
            mocked_post.return_value.json.return_value = {'response': _MOCK_DEFINITION}
            self.client.get('/api/glossary/emptyterm')

        response = self.client.put('/api/glossary/emptyterm',
                                   json={'definition': '   '},
                                   content_type='application/json')
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('error', data)

    def test_delete_term_endpoint(self):
        """Test DELETE /api/glossary/<term> - delete existing term"""
        # First create a term
        with mock.patch('app.requests.post') as mocked_post:
            mocked_post.return_value.json.return_value = {'response': _MOCK_DEFINITION}
            self.client.get('/api/glossary/deleteterm')

        # Now delete it
        response = self.client.delete('/api/glossary/deleteterm')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('message', data)

        # Verify it's gone
        response2 = self.client.get('/api/glossary')
        data2 = response2.get_json()
        terms = [item['term'] for item in data2]
        self.assertNotIn('deleteterm', terms)

    def test_delete_nonexistent_term(self):
        """Test DELETE /api/glossary/<term> - 404 for non-existent term"""
        response = self.client.delete('/api/glossary/nonexistent')
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertIn('error', data)

    def test_non_financial_term_rejected(self):
        """Test that non-financial terms are rejected with 400"""
        response = self.client.get('/api/glossary/apple')
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('error', data)
        self.assertIn('financial', data['error'].lower())

    def test_ai_mode_disabled_returns_503(self):
        """Test that AI mode disabled returns 503"""
        # Create a new test client with DISABLE_AI_MODE=true
        import app as app_module
        original_disable = app_module.DISABLE_AI_MODE
        app_module.DISABLE_AI_MODE = True
        try:
            response = self.client.get('/api/glossary/testdisabled')
            self.assertEqual(response.status_code, 503)
            data = response.get_json()
            self.assertEqual(data['definition'], 'AI-Mode is disabled in CI/CD')
        finally:
            app_module.DISABLE_AI_MODE = original_disable

    def test_mcp_proxy_disabled_in_ci(self):
        """Test that MCP proxy returns 503 when disabled"""
        import app as app_module
        original_disable = app_module.DISABLE_MCP_PROXY
        app_module.DISABLE_MCP_PROXY = True
        try:
            response = self.client.post('/api/mcp/glossary-lookup', data={'term': 'ETF'})
            self.assertEqual(response.status_code, 503)
            data = response.get_json()
            self.assertEqual(data['error'], 'MCP proxy is disabled in CI/CD environment')
        finally:
            app_module.DISABLE_MCP_PROXY = original_disable

    def test_rag_proxy_disabled_in_ci(self):
        """Test that RAG proxy returns 503 when disabled"""
        import app as app_module
        original_disable = app_module.DISABLE_RAG_PROXY
        app_module.DISABLE_RAG_PROXY = True
        try:
            response = self.client.post('/api/rag/answer', json={'query': 'What is an ETF?'})
            self.assertEqual(response.status_code, 503)
            data = response.get_json()
            self.assertEqual(data['error'], 'RAG proxy is disabled in CI/CD environment')
        finally:
            app_module.DISABLE_RAG_PROXY = original_disable

    def test_multi_agent_proxy_disabled_in_ci(self):
        """Test that Multi-Agent proxy returns 503 when disabled"""
        import app as app_module
        original_disable = app_module.DISABLE_MULTI_AGENT_PROXY
        app_module.DISABLE_MULTI_AGENT_PROXY = True
        try:
            response = self.client.post('/api/multi-agent/workflow', json={'task': 'test', 'evidence': {}})
            self.assertEqual(response.status_code, 503)
            data = response.get_json()
            self.assertEqual(data['error'], 'Multi-Agent proxy is disabled in CI/CD environment')
        finally:
            app_module.DISABLE_MULTI_AGENT_PROXY = original_disable

    def test_health_endpoint(self):
        """Test GET /health - liveness probe"""
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['status'], 'ok')

    def test_ollama_unreachable_returns_500(self):
        """Test that unreachable Ollama returns 500 with error"""
        with mock.patch('app.requests.post') as mocked_post:
            mocked_post.side_effect = Exception('Connection refused')
            response = self.client.get('/api/glossary/connectionerror')
            self.assertEqual(response.status_code, 500)
            data = response.get_json()
            self.assertIn('error', data)


if __name__ == '__main__':
    unittest.main()
