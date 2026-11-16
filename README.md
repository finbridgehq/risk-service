# Vankoo Risk Service

Microservicio de evaluación de riesgo de Vankoo. Decide si la factura de cada subasta se puede financiar y, si se puede, la califica con **A, B o C** antes de que la MYPE pueda cotizarla. La decisión se la entrega a Investment.

Califica al **pagador** con datos públicos (padrón de SUNAT, agentes de retención, sujetos sin capacidad operativa, deuda coactiva, sanciones de OECE y OEFA), noticias en internet leídas por IA (OpenAI), una central de riesgos **simulada** y reglas de puntos explicables: ver [docs/SCORING_RULES.md](docs/SCORING_RULES.md).

Decide también si la **MYPE** es verde: lee con IA el certificado ambiental (ISO 14001 o ISO 50001) que subió a su perfil, lo comprueba con reglas fijas contra SUNAT y OEFA y marca como verdes sus subastas: ver [docs/GREEN_RULES.md](docs/GREEN_RULES.md).

Y verifica a la **MYPE** (KYC): comprueba sin salir a internet la firma digital de SUNAT de su ficha RUC, la lee y la contrasta con el padrón y la lista SSCO, con reglas fijas y sin IA: ver [docs/KYC_RULES.md](docs/KYC_RULES.md).

## Qué hace

1. Escucha `AuctionCreated` en el tópico `investment.auction-lifecycle.v1`.
2. Consulta lo que SUNAT dice del pagador en su copia local de los padrones (contexto `registries`).
3. Decide con las reglas de puntos y guarda la evaluación junto con el evento procesado, en la misma transacción.
4. Se la entrega a Investment, y reintenta mientras Investment no responda:
   - si es elegible, con `PUT /api/v1/internal/auctions/{auctionId}/evaluation`: la subasta pasa a `DRAFT` y la MYPE ya puede cotizarla;
   - si no, con `POST /api/v1/internal/auctions/{auctionId}/rejection`: la subasta pasa a `REJECTED` con el motivo.

Y, para el verde (contexto `sustainability`):

1. Escucha `SustainabilityCertificateSubmitted` en `vankoo.profile.events`.
2. Descarga el certificado del bucket de Profile, lo lee con OpenAI y lo decide con las reglas `green-v1`.
3. Publica `GreenCertificationIssued` en `risk.green-certifications.v1` desde un outbox, para que Profile lo muestre.
4. Al calificar una subasta elegible, adjunta el certificado de su MYPE si sigue siendo verde ese día.

Y, para el KYC (contexto `verification`):

1. Escucha `CompanyVerificationRequested` en `vankoo.profile.events`, en su propio grupo.
2. Descarga la ficha RUC del bucket de Profile, verifica su firma con pyHanko y la decide con las reglas `kyc-v1`.
3. Publica `CompanyVerificationIssued` en `risk.company-verifications.v1` desde el outbox; Profile decide el estado KYC con eso.

## Los padrones de SUNAT

El contexto `registries` guarda una copia local de:

- el **padrón reducido del RUC**: unos 18 millones de RUC, con RUC, razón social, estado, condición y ubigeo; unos 2 GB en PostgreSQL;
- el **padrón de agentes de retención y percepción del IGV**: unas 7.800 filas;
- las listas de **sanciones**, que son pequeñas: SSCO de SUNAT (unas 770), deuda coactiva de SUNAT (unas 9.000), inhabilitados y multas de OECE (unas 14.000) e infractores ambientales de OEFA (unos 4.300).

Se actualizan:

```bash
uv run python -m registries refresh                    # los dos
uv run python -m registries refresh --source agents    # solo uno (ver --help)
uv run python -m registries refresh --force            # aunque no haya versión nueva
```

Con el servicio en marcha, se refrescan solos al arrancar y cada día a las 04:00 de Lima. Corren como subproceso para no bloquear la API. Si SUNAT no publicó nada nuevo (mismo `Last-Modified`), no se descarga nada.

La primera carga del padrón descarga unos 400 MB y tarda unos minutos. Mientras tanto, las subastas salen **C** («padrón no disponible») y no se rechazan. La copia anterior sigue en uso hasta que la nueva está entera.

El detalle está en [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Requisitos previos

- Python 3.12 y [uv](https://docs.astral.sh/uv/).
- Docker, para PostgreSQL, Kafka e Investment (el compose de `vankoo-infra`).

## Ejecución local

```bash
uv sync
cp .env.example .env
```

Levantar las dependencias desde `vankoo-infra`:

```bash
docker compose up -d risk-db-postgres kafka-broker investment-service
```

Aplicar las migraciones y arrancar:

```bash
uv run alembic upgrade head
uv run fastapi dev main.py
```

La API queda en `http://localhost:8000` y la documentación en `/docs`.

**Un solo worker.** El consumidor de Kafka y el repartidor viven en el proceso de la API. Con `--workers 2` habría dos de cada uno. Para escalar se levantan más contenedores en el mismo grupo de consumidores.

## Uso con Docker

El servicio está en el compose de `vankoo-infra` como `risk-service` (puerto 8000) con su base `risk-db-postgres` (puerto 5435). Al arrancar, el contenedor aplica las migraciones.

```bash
docker compose up -d --build risk-service
```

## Endpoints

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/api/v1/risk-assessments/{auctionId}` | La evaluación de una subasta (elegible o no, nota, puntaje, factores, si es verde y con qué certificado) y el estado de su entrega a Investment. Interna |
| GET | `/api/v1/mype/risk-assessments/{auctionId}` | La misma evaluación para la MYPE dueña de la factura: elegible o no, nota, puntaje, cada factor con sus puntos y el motivo del rechazo, sin datos de entrega. Pide `X-User-Id` (401 sin ella) y responde 404 si la subasta es de otra MYPE |
| GET | `/health` | Vivo |
| GET | `/health/ready` | Listo: base de datos, consumidores, repartidor y relay arriba (503 si no) |

El gateway solo expone `/risk/api/v1/mype/**`, protegido con JWT, que pone `X-User-Id`. El resto no se rutea.

## Variables de entorno

| Variable | Por defecto | Para qué |
|---|---|---|
| `DATABASE_URL` | — (obligatoria) | `postgresql+asyncpg://…` |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | `kafka-broker:9094` dentro de Docker |
| `KAFKA_GROUP_ID` | `risk-auction-assessment-v1` | Grupo de consumidores |
| `KAFKA_AUTO_OFFSET_RESET` | `latest` | Dónde empieza un grupo nuevo; ver por qué en la arquitectura |
| `KAFKA_CONSUMER_ENABLED` | `true` | Apagar los dos consumidores en tests o para solo migrar |
| `KAFKA_PRODUCER_ENABLED` | `true` | Apagar el relay del outbox (`risk.green-certifications.v1`) |
| `INVESTMENT_BASE_URL` | `http://localhost:8082` | Investment directo, nunca el gateway |
| `INVESTMENT_DELIVERY_ENABLED` | `true` | Apagar el repartidor |
| `REGISTRY_REFRESH_ENABLED` | `true` | Refrescar los padrones desde el servicio |
| `REGISTRY_REFRESH_HOUR` | `4` | Hora del refresco diario (zona `REGISTRY_TIMEZONE`, `America/Lima`) |
| `REGISTRY_TAXPAYERS_URL` | el ZIP de SUNAT | Dónde está el padrón reducido |
| `REGISTRY_AGENTS_URL_TEMPLATE` | el ZIP mensual de datos abiertos | Dónde está el padrón de agentes (`{period}` = `YYYYMM`) |
| `REGISTRY_SHELL_COMPANIES_URL`, `REGISTRY_COACTIVE_DEBTORS_URL`, `REGISTRY_OECE_DISQUALIFICATIONS_URL`, `REGISTRY_OECE_FINES_URL`, `REGISTRY_ENVIRONMENTAL_OFFENDERS_URL` | las de SUNAT, OECE y OEFA | Dónde están las listas de sanciones |
| `CREDIT_BUREAU_ENABLED` | `true` | Consultar la central de riesgos **simulada** |
| `OPENAI_API_KEY` | — | Clave de OpenAI para buscar noticias; sin ella el paso se salta (nunca se registra en logs) |
| `NEWS_ENABLED` | `true` | Buscar noticias negativas del pagador |
| `NEWS_MODEL` | `gpt-6-luna` | Modelo de OpenAI que busca y lee |
| `NEWS_MAX_SEARCHES` | `5` | Búsquedas como máximo por pagador (cada una cuesta unos $0,01) |
| `NEWS_CACHE_DAYS` | `7` | Cuánto se reutiliza la búsqueda de un pagador |
| `GREEN_ENABLED` | `true` | Leer los certificados verdes (con la misma `OPENAI_API_KEY`); sin clave, las subidas quedan sin decidir |
| `GREEN_MODEL` | `gpt-6-luna` | Modelo de OpenAI que lee el certificado |
| `GREEN_REASONING_EFFORT` | `low` | Cuánto razona: solo transcribe |
| `GREEN_DOCUMENTS_BASE_URL` | `http://localhost:9100/vankoo-profile-documents` | El bucket de Profile **visto desde este servicio** (`http://minio:9000/…` dentro de Docker) |
| `GREEN_MAX_BYTES` | `10485760` | Tamaño máximo del certificado |
| `GREEN_PROFILE_GROUP_ID` | `risk-profile-sustainability-v1` | Grupo de consumidores del tópico de Profile |
| `GREEN_PROFILE_OFFSET_RESET` | `earliest` | Dónde empieza ese grupo la primera vez. `earliest` a propósito: el tópico de Profile puede crearse después de que arranque risk, y con `latest` se saltaría el primer certificado |
| `KYC_MAX_BYTES` | `5242880` | Tamaño máximo de la ficha RUC (se descarga con `GREEN_DOCUMENTS_BASE_URL`) |
| `KYC_PROFILE_GROUP_ID` | `risk-profile-verification-v1` | Grupo de consumidores del tópico de Profile para el KYC |
| `KYC_PROFILE_OFFSET_RESET` | `earliest` | Dónde empieza ese grupo la primera vez, como `GREEN_PROFILE_OFFSET_RESET` |
| `KYC_DEMO_CA_PATH` | — | **Parche temporal para demos**: la CA de demostración (`python -m verification demo-ca`). Con ella, las fichas de demo se aceptan marcadas `demo`. **Nunca en producción** |
| `DOCS_ENABLED` | `true` | Servir `/docs` |

## Pruebas

```bash
uv run ruff check .
uv run mypy .
uv run pytest
```

Los tests usan dobles en memoria: no necesitan PostgreSQL, Kafka ni una clave de OpenAI (las respuestas de OpenAI se simulan).

## Información adicional

- Sigue la skill `ddd-fastapi`, instalada en `.agents/skills/ddd-fastapi` (se actualiza con `npx skills update`).
- Contratos que consume: `docs/contracts/auction-lifecycle/v1` en `vankoo-investment-service` y `SustainabilityCertificateSubmitted` y `CompanyVerificationRequested` en `vankoo-profile-service`. Sus ejemplos están copiados en `tests/contracts/`.
- Contratos que publica: [docs/contracts/green-certifications/v1](docs/contracts/green-certifications/v1/README.md) y [docs/contracts/company-verifications/v1](docs/contracts/company-verifications/v1/README.md).
- Convenciones del repo: [docs/CONVENTIONS.md](docs/CONVENTIONS.md).
