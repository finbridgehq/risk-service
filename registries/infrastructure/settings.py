"""Settings the Registries context owns, read from ``REGISTRY_*`` variables."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class RegistrySettings(BaseSettings):
    """Where SUNAT publishes its registries, and when to refresh the local copy.

    Attributes:
        taxpayers_url (str): The padrón reducido del RUC (a ZIP of about 400 MB,
            rebuilt every day).
        agents_url_template (str): The monthly registry of IGV withholding and
            perception agents on the national open-data portal; ``{period}`` is
            ``YYYYMM``.
        agents_months_back (int): How many months back to look for the latest
            agents file, since the current month may not be published yet.
        shell_companies_url (str): SUNAT's list of taxpayers without operating
            capacity (SSCO), XLSX, monthly.
        coactive_debtors_url (str): SUNAT's list of the largest debts in coactive
            collection, XLSX, weekly.
        oece_disqualifications_url (str): Suppliers barred by OECE, CSV, weekly.
        oece_fines_url (str): Unpaid OECE fines, CSV, weekly.
        environmental_offenders_url (str): OEFA's register of sanctioned
            offenders, as its portal serves it (JSON). Undocumented: it can change.
        environmental_offenders_version_url (str): The portal's "updated to…"
            title, used as the register's version.
        environmental_offenders_fallback_url (str): The same register on the
            open-data portal (CSV), older, used if the portal fails.
        user_agent (str): Sent with every request. The open-data portal answers
            418 to clients that do not look like a browser.
        download_timeout (float): Seconds to wait for any single read while downloading.
        refresh_enabled (bool): Refresh the registries from the running service:
            once at start-up and every day at ``refresh_hour``.
        refresh_hour (int): Hour of the daily refresh, in ``timezone``. SUNAT
            rebuilds the padrón around 02:30 Lima time.
        timezone (str): Time zone of ``refresh_hour``.
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="REGISTRY_", extra="ignore")

    taxpayers_url: str = "https://www2.sunat.gob.pe/padron_reducido_ruc.zip"
    agents_url_template: str = (
        "https://www.datosabiertos.gob.pe/sites/default/files/padron_agentes_retencion_percepcion_igv_{period}.zip"
    )
    agents_months_back: int = 4
    shell_companies_url: str = "https://www.sunat.gob.pe/padronesnotificaciones/ssco/sujesincapacidadOperativa.xlsx"
    coactive_debtors_url: str = (
        "https://www.sunat.gob.pe/padronesnotificaciones/deudaExigibleControlDeuda/pgdt-deudaPadron.xlsx"
    )
    oece_disqualifications_url: str = (
        "https://conosce.osce.gob.pe/buscador/assets/67ae6c4a/reportes/sancionados/sancionados.csv"
    )
    oece_fines_url: str = "https://conosce.osce.gob.pe/buscador/assets/67ae6c4a/reportes/sancionados/sancionados_multa.csv"
    environmental_offenders_url: str = (
        "https://sistemas.oefa.gob.pe/Portalpifa/mostrarDetalleRasmaResumen.do?cod_adm=&nameCategory="
    )
    environmental_offenders_version_url: str = (
        "https://sistemas.oefa.gob.pe/Portalpifa/obtenerTituloActualizacionRuias.do"
    )
    environmental_offenders_fallback_url: str = (
        "https://www.datosabiertos.gob.pe/sites/default/files/"
        "1a_Registro%20%C3%9Anico%20de%20Infractores%20Ambientales%20Sancionados.csv"
    )
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 VankooRiskService/0.2"
    )
    download_timeout: float = 120.0
    refresh_enabled: bool = True
    refresh_hour: int = 4
    timezone: str = "America/Lima"


registry_settings = RegistrySettings()
