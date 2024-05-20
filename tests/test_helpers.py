import unittest
from unittest.mock import patch
import logging

from utils.helpers import get_env_variable

class TestHelpers(unittest.TestCase):

    @patch('utils.helpers.os.getenv')
    def test_get_env_variable_success(self, mock_getenv):
        mock_getenv.return_value = 'some_value'
        result = get_env_variable('TEST_VAR')
        self.assertEqual(result, 'some_value')
        mock_getenv.assert_called_once_with('TEST_VAR')
    
    @patch('utils.helpers.os.getenv')
    def test_get_env_variable_missing_required(self, mock_getenv):
        mock_getenv.return_value = None
        with self.assertRaises(ValueError) as context:
            get_env_variable('MISSING_VAR')
        self.assertEqual(str(context.exception), 'Missing required environment variable: MISSING_VAR')
        mock_getenv.assert_called_once_with('MISSING_VAR')

    @patch('utils.helpers.os.getenv')
    def test_get_env_variable_not_required(self, mock_getenv):
        mock_getenv.return_value = None
        result = get_env_variable('OPTIONAL_VAR', required=False)
        self.assertIsNone(result)
        mock_getenv.assert_called_once_with('OPTIONAL_VAR')

    @patch('utils.helpers.os.getenv')
    def test_get_env_variable_empty_required(self, mock_getenv):
        mock_getenv.return_value = ''
        with self.assertRaises(ValueError) as context:
            get_env_variable('EMPTY_VAR')
        self.assertEqual(str(context.exception), 'Missing required environment variable: EMPTY_VAR')
        mock_getenv.assert_called_once_with('EMPTY_VAR')

    @patch('utils.helpers.os.getenv')
    def test_get_env_variable_empty_not_required(self, mock_getenv):
        mock_getenv.return_value = ''
        result = get_env_variable('EMPTY_VAR', required=False)
        self.assertEqual(result, '')
        mock_getenv.assert_called_once_with('EMPTY_VAR')

if __name__ == '__main__':
    unittest.main()
