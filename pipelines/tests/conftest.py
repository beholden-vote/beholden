"""Shared fixtures for every test module in this directory (WO-32).

`slice_dirs` and `local_dirs` are defined in test_pipeline.py, which is where
they have always lived. Re-exporting them here makes them available to sibling
modules without moving 3,000 lines of fixture data, so a new feature's tests can
go in their own `test_<feature>.py` instead of being appended to one file that
every concurrent branch would then conflict on.
"""
from test_pipeline import local_dirs, slice_dirs  # noqa: F401


def pytest_configure(config):
    """No test may see the bucket credentials. The nightly runs this suite with the real R2
    secrets in its environment, and code that falls back to the lake (rawlake hydration,
    roster last-good restore) would then read PRODUCTION data inside a unit test. Removed once,
    before any fixture of any scope runs; a test that needs the variables sets them itself."""
    import os
    for name in ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        os.environ.pop(name, None)
