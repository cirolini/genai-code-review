import unittest
from unittest.mock import patch, MagicMock
import logging
from main import main, get_env_vars, process_files, process_patch, analyze_commit_files, analyze_patch, create_review_prompt

class TestMainModule(unittest.TestCase):

    @patch('main.get_env_vars')
    @patch('main.GithubClient')
    @patch('main.OpenAIClient')
    def test_main_files_mode(self, MockOpenAIClient, MockGithubClient, mock_get_env_vars):
        mock_get_env_vars.return_value = {
            'GITHUB_TOKEN': 'fake_github_token',
            'OPENAI_API_KEY': 'fake_openai_api_key',
            'OPENAI_MODEL': 'gpt-3.5-turbo',
            'OPENAI_TEMPERATURE': 0.5,
            'OPENAI_MAX_TOKENS': 1000,
            'MODE': 'files',
            'GITHUB_PR_ID': 1,
            'LANGUAGE': 'en',
            'CUSTOM_PROMPT': None
        }

        with patch('main.process_files') as mock_process_files:
            main()
            mock_process_files.assert_called_once()

    @patch('main.get_env_vars')
    @patch('main.GithubClient')
    @patch('main.OpenAIClient')
    def test_main_patch_mode(self, MockOpenAIClient, MockGithubClient, mock_get_env_vars):
        mock_get_env_vars.return_value = {
            'GITHUB_TOKEN': 'fake_github_token',
            'OPENAI_API_KEY': 'fake_openai_api_key',
            'OPENAI_MODEL': 'gpt-3.5-turbo',
            'OPENAI_TEMPERATURE': 0.5,
            'OPENAI_MAX_TOKENS': 1000,
            'MODE': 'patch',
            'GITHUB_PR_ID': 1,
            'LANGUAGE': 'en',
            'CUSTOM_PROMPT': None
        }

        with patch('main.process_patch') as mock_process_patch:
            main()
            mock_process_patch.assert_called_once()

    @patch('main.get_env_variable')
    def test_get_env_vars(self, mock_get_env_variable):
        mock_get_env_variable.side_effect = lambda var, required: {
            'OPENAI_API_KEY': 'fake_openai_api_key',
            'GITHUB_TOKEN': 'fake_github_token',
            'GITHUB_PR_ID': '1',
            'OPENAI_MODEL': 'gpt-3.5-turbo',
            'OPENAI_TEMPERATURE': '0.5',
            'OPENAI_MAX_TOKENS': '1000',
            'MODE': 'files',
            'LANGUAGE': 'en',
            'CUSTOM_PROMPT': None
        }.get(var, None)

        env_vars = get_env_vars()
        self.assertEqual(env_vars['OPENAI_API_KEY'], 'fake_openai_api_key')
        self.assertEqual(env_vars['GITHUB_TOKEN'], 'fake_github_token')
        self.assertEqual(env_vars['GITHUB_PR_ID'], 1)
        self.assertEqual(env_vars['OPENAI_TEMPERATURE'], 0.5)

    def test_create_review_prompt(self):
        content = "def foo(): pass"
        language = "en"
        custom_prompt = None

        prompt = create_review_prompt(content, language, custom_prompt)
        self.assertIn("Please review the following code", prompt)

    @patch('main.GithubClient')
    @patch('main.OpenAIClient')
    def test_process_files(self, MockGithubClient, MockOpenAIClient):
        github_client = MockGithubClient()
        openai_client = MockOpenAIClient()
        github_client.get_pr.return_value.get_commits.return_value = [MagicMock(sha='abc123')]

        process_files(github_client, openai_client, 1, 'en', None)
        github_client.get_pr.assert_called_with(1)
        openai_client.generate_response.assert_called()

    @patch('main.GithubClient')
    @patch('main.OpenAIClient')
    def test_process_patch(self, MockGithubClient, MockOpenAIClient):
        github_client = MockGithubClient()
        openai_client = MockOpenAIClient()
        github_client.get_pr_patch.return_value = 'diff --git a/file b/file'

        process_patch(github_client, openai_client, 1, 'en', None)
        github_client.get_pr_patch.assert_called_with(1)
        openai_client.generate_response.assert_called()

if __name__ == '__main__':
    unittest.main()