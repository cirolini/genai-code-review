import unittest
from unittest.mock import patch, MagicMock
from clients.openai_client import OpenAIClient  # Substitua 'your_module' pelo nome do seu módulo.

class TestOpenAIClient(unittest.TestCase):

    @patch('clients.openai_client.OpenAI')
    def setUp(self, MockOpenAI):
        self.mock_openai = MockOpenAI.return_value
        self.mock_openai.chat.completions.create.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content="Test response"))])
        self.client = OpenAIClient(model="gpt-3.5-turbo", temperature=0.7, max_tokens=150)

    def test_initialization(self):
        self.assertEqual(self.client.model, "gpt-3.5-turbo")
        self.assertEqual(self.client.temperature, 0.7)
        self.assertEqual(self.client.max_tokens, 150)
        
    def test_generate_response_success(self):
        prompt = "Hello, how are you?"
        response = self.client.generate_response(prompt)
        self.assertEqual(response, "Test response")
        self.mock_openai.chat.completions.create.assert_called_once_with(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an expert Developer."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=150
        )

    @patch('clients.openai_client.logging')
    def test_generate_response_exception(self, mock_logging):
        self.mock_openai.chat.completions.create.side_effect = Exception("API error")
        with self.assertRaises(Exception) as context:
            self.client.generate_response("This will fail.")
        self.assertTrue("API error" in str(context.exception))
        
if __name__ == '__main__':
    unittest.main()
