"""Trusted-extraction framework for Tier-A bulk disclosure sources.

Implements docs/TRUSTED-EXTRACTION.md: a pinned, versioned SourceContract
(contract.py) plus fail-closed reconciliation gates (reconcile.py). No model is
ever in the extraction path — every published fact is a verbatim cell copied from
a content-hashed snapshot and is deterministically traceable to its source.
"""
