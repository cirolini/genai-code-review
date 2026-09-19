"""
Helper functions.

Provides a single helper for reading environment variables and enforcing that
required ones are present and non-empty.
"""

import logging
import os

logger = logging.getLogger(__name__)

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
    logger.info("Retrieving environment variable: %s", key)
    value = os.getenv(key)
    if required and not value:
        logger.error("Missing required environment variable: %s", key)
        raise ValueError(f"Missing required environment variable: {key}")
    logger.info("Successfully retrieved environment variable: %s", key)
    return value
