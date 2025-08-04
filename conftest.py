"""
Pytest configuration file for the Funding Rate Strategy application.

This module configures the Python path to include the project root directory,
ensuring that imports work correctly during test execution regardless of
which directory the tests are run from.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))