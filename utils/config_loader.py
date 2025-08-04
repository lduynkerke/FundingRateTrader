"""
Configuration loading utility for the Funding Rate Strategy application.

This module provides functionality to load application configuration from YAML files.
It offers a simple interface to access configuration settings throughout the application,
ensuring consistent configuration across all components.
"""

import yaml

def load_config(path: str = "config.yaml") -> dict:
    """
    Loads the YAML configuration file.

    :param path: Path to the config file.
    :type path: str
    :return: Parsed configuration as dictionary.
    :rtype: dict
    """
    with open(path, 'r') as file:
        return yaml.safe_load(file)
