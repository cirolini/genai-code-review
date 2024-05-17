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
    logging.info(f"Retrieving environment variable: {key}")
    value = os.getenv(key)
    if required and not value:
        logging.error(f"Missing required environment variable: {key}")
        raise ValueError(f"Missing required environment variable: {key}")
    logging.info(f"Successfully retrieved environment variable: {key}")
    return value

