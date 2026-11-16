"""Company names, written so the same company compares equal.

Shared because every context that checks a document against SUNAT's padrón
compares names the same way: the green certificates and the ficha RUC.
"""
import unicodedata

# Legal forms dropped from the end of a name before comparing, as word sequences
# once punctuation is gone: "S.A.C." becomes "S A C".
LEGAL_FORMS = tuple(
    tuple(form.split())
    for form in (
        "SOCIEDAD ANONIMA CERRADA",
        "SOCIEDAD ANONIMA ABIERTA",
        "SOCIEDAD ANONIMA",
        "SOCIEDAD COMERCIAL DE RESPONSABILIDAD LIMITADA",
        "EMPRESA INDIVIDUAL DE RESPONSABILIDAD LIMITADA",
        "S A C",
        "SAC",
        "S A A",
        "SAA",
        "S A",
        "SA",
        "S R L",
        "SRL",
        "E I R L",
        "EIRL",
    )
)


def normalize_company_name(name: str) -> str:
    """Write a company name so the same company compares equal.

    Upper case, no accents, no punctuation, single spaces, and without the
    legal form at the end: «Agroexport Verde S.A.C.» and «AGROEXPORT VERDE
    SOCIEDAD ANONIMA CERRADA» both become ``AGROEXPORT VERDE``.

    Args:
        name (str): A name as printed or registered.

    Returns:
        str: The name to compare.
    """
    decomposed = unicodedata.normalize("NFKD", name.upper())
    letters = "".join(char for char in decomposed if not unicodedata.combining(char))
    words = "".join(char if char.isalnum() else " " for char in letters).split()
    for form in LEGAL_FORMS:
        if len(words) > len(form) and tuple(words[-len(form) :]) == form:
            words = words[: -len(form)]
            break
    return " ".join(words)
