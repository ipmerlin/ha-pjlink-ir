"""Enable custom integrations in actual Home Assistant tests."""

import pytest


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield
