"""pytest config for the trend scraper: --live opts into network tests."""
import pytest


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", default=False,
                     help="run live (network) tests")


def pytest_collection_modifyitems(session, config, items):
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="live test: needs --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
