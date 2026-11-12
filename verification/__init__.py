"""Verification bounded context.

Checks that a MYPE is who it says it is (its KYC): the ficha RUC it uploaded to
its profile, signed by SUNAT, against SUNAT's padrón and the SSCO list, under
fixed rules (``kyc-v1``). It only gives the evidence and a recommendation;
Profile decides the MYPE's KYC status from it.
"""
