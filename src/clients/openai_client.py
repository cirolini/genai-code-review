"""
Client for the OpenAI API.

Wraps the chat completions endpoint and returns the model's reply as text.
"""

import logging

from openai import OpenAI

logger = logging.getLogger(__name__)

class OpenAIClient:
    """
    A client for interacting with the OpenAI API to generate responses using a specified model.
    """

    def __init__(self, model, temperature, max_tokens):
        """
        Initialize the OpenAIClient with a model, temperature, and token limit.

        The API key is read from the OPENAI_API_KEY environment variable by the
        OpenAI SDK itself.

        Args:
            model (str): The OpenAI model to use.
            temperature (float): The sampling temperature.
            max_tokens (int): The maximum number of tokens to generate.
        """
        try:
            self.client = OpenAI()
            self.model = model
            self.temperature = temperature
            self.max_tokens = max_tokens
            logger.info(
                "OpenAI client initialized successfully, "
                "Model: %s, temperature: %s, max tokens: %s",
                self.model,
                self.temperature,
                self.max_tokens
            )
        except Exception as e:
            logger.error("Error initializing OpenAI client: %s", e)
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
            logger.info("Generating response from OpenAI model.")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert Developer."},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            logger.info("Response generated successfully.")
            return response.choices[0].message.content
        except Exception as e:
            logger.error("Error generating response from OpenAI model: %s", e)
            raise
