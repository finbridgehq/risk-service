"""The Registries bounded context: SUNAT's public registries, kept as a local copy.

SUNAT publishes the taxpayer registry (padrón reducido del RUC) and the
registry of IGV withholding and perception agents as downloadable files. This
context downloads them, loads them into PostgreSQL, and answers one question
for the other contexts: what SUNAT says about a RUC.
"""
