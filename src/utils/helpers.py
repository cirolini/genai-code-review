"""
Este módulo contém funções auxiliares para o projeto.
Este módulo fornece uma função para recuperar variáveis de ambiente e garantir que elas não 
estejam vazias, se necessário.
"""

import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_env_variable(key, required=True):
    """
    Retrieve an environment variable and ensure it is not empty if required.

    Args:
        key (str): The key of the environment variable.
        required (bool): Whether the environment variable is required.

    Returns:
        str: The value of the environment variable or None if not required and missing.

    Raises:
        ValueError: If the environment variable is required and missing or empty.
    """
    logging.info("Retrieving environment variable: %s", key)
    value = os.getenv(key)
    if required and not value:
        logging.error("Missing required environment variable: %s", key)
        raise ValueError(f"Missing required environment variable: {key}")
    logging.info("Successfully retrieved environment variable: %s", key)
    return value
