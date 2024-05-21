"""
Este módulo contém a classe OpenAIClient, que é usada para interagir com a API do OpenAI.
A classe OpenAIClient pode ser usada para gerar respostas de um modelo especificado do OpenAI.
"""

import logging
from openai import OpenAI

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class OpenAIClient:
    """
    A client for interacting with the OpenAI API to generate responses using a specified model.
    """

    def __init__(self, model, temperature, max_tokens):
        """
        Initialize the OpenAIClient with API key, model, temperature, and max tokens.

        Args:
            api_key (str): The OpenAI API key.
            model (str): The OpenAI model to use.
            temperature (float): The sampling temperature.
            max_tokens (int): The maximum number of tokens to generate.
        """
        try:
            self.client = OpenAI()
            self.model = model
            self.temperature = temperature
            self.max_tokens = max_tokens
            logging.info(
                "OpenAI client initialized successfully, "
                "Model: %s, temperature: %s, max tokens: %s",
                self.model,
                self.temperature,
                self.max_tokens
            )
        except Exception as e:
            logging.error("Error initializing OpenAI client: %s", e)
            raise

    def generate_response(self, prompt):
        """
        Generate a response from the OpenAI model based on the given prompt.

        Args:
            prompt (str): The prompt to send to the OpenAI API.

        Returns:
            str: The generated response from the OpenAI model.

        Raises:
            Exception: If there is an error generating the response.
        """
        try:
            logging.info("Generating response from OpenAI model.")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert Developer."},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            logging.info("Response generated successfully.")
            return response.choices[0].message.content
        except Exception as e:
            logging.error("Error generating response from OpenAI model: %s", e)
            raise
