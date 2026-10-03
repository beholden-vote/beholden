"""Shared fixtures for every test module in this directory (WO-32).

`slice_dirs` and `local_dirs` are defined in test_pipeline.py, which is where
they have always lived. Re-exporting them here makes them available to sibling
modules without moving 3,000 lines of fixture data, so a new feature's tests can
go in their own `test_<feature>.py` instead of being appended to one file that
every concurrent branch would then conflict on.
"""
from test_pipeline import local_dirs, slice_dirs  # noqa: F401
