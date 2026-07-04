"""Pipeline entrypoints invoked by the Makefile / etl-nightly workflow:
`python -m beholden_etl.jobs.{fetch,transform,build,publish}`.

Stage boundary = the raw lake (dist/raw) and the serving dir (dist/data), so any
stage can run standalone against artifacts the previous one landed. Each module
exposes `run()` and a `__main__` guard.
"""
