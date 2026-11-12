"""Sustainability bounded context.

Decides whether a MYPE is green: it reads the environmental certificate the
MYPE uploaded to its profile, checks it against fixed rules (``green-v1``) and
tells Profile the result. The decision is the MYPE's, not an invoice's; the
Assessments context asks it, for each auction, whether its MYPE is still green.
"""
