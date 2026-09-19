"""Test configuration and global fixtures.
Provides deterministic test secrets and isolated test environments.
"""

import pytest
from packages.shared.config import settings
from packages.payments.dodo import dodo_provider

# Ensure authoritative Dodo webhook secret is configured for all automated test runs
settings.DODO_WEBHOOK_SECRET = "whsec_test_secret_for_automated_tests_only"
dodo_provider.webhook_secret = settings.DODO_WEBHOOK_SECRET
