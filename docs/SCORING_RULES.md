# Reglas de calificación (`points-v3`)

La política es `PointsGradingPolicy` (`assessments/domain/services.py`). Cada evaluación guarda sus factores con código, puntos y detalle, y los devuelve `GET /api/v1/risk-assessments/{auctionId}`. Así cualquier nota se puede explicar.

## Datos que usa

| Fuente | Qué aporta | Cada cuánto |
|---|---|---|
| Padrón reducido del RUC (SUNAT) | Si el RUC existe, estado, condición del domicilio, razón social | Diario |
| Agentes de retención y percepción del IGV (datos abiertos) | Si SUNAT lo designó agente | Mensual |
| Sujetos sin capacidad operativa, SSCO (SUNAT) | Empresas «de papel»: sus comprobantes no sustentan operaciones reales | Mensual |
| Mayor deuda en cobranza coactiva (SUNAT) | Deuda coactiva de más de 5 UIT y su monto | Semanal |
| Proveedores inhabilitados y multados (OECE, ex OSCE) | Inhabilitaciones con sus fechas; multas impagas (las pagadas salen de la lista) | Semanal |
| Infractores ambientales, RUIAS (OEFA) | Infracciones sancionadas en los últimos 5 años | Según OEFA (la última, noviembre de 2025) |
| Central de riesgos **simulada** | Calificación SBS (Normal, CPP, Deficiente, Dudoso, Pérdida) | En cada evaluación |
| Noticias en internet, leídas por IA (OpenAI `gpt-6-luna` con búsqueda web) | Fraude, quiebra, corrupción, juicios por impago, sanciones ambientales | Una búsqueda por pagador cada 7 días |
| La subasta (`AuctionCreated`) | RUC y nombre del pagador según la factura, vencimiento | En cada evento |

SUNAFIL no publica ningún archivo descargable de empresas sancionadas, así que no se usa.

Ningún archivo de SUNAT trae la fecha de inscripción del RUC, así que la antigüedad no cuenta.

## 1. Filtro: la factura no es elegible

| Código | Cuándo |
|---|---|
| `PAYER_NOT_IN_REGISTRY` | El RUC del pagador no figura en el padrón |
| `PAYER_SHELL_COMPANY` | SUNAT lo declaró sujeto sin capacidad operativa (SSCO) |
| `PAYER_NOT_ACTIVE` | El estado no es `ACTIVO` (baja, suspensión…) |
| `PAYER_DOMICILE_NOT_FOUND` | La condición es `NO HABIDO` o `NO HALLADO…` |

La subasta pasa a `REJECTED` en Investment con el código y el motivo, y la MYPE lo ve en el detalle de su factura.

## 2. Puntos: se parte de 40

| Código | Puntos | Cuándo |
|---|---|---|
| `WITHHOLDING_AGENT` | +20 | Agente de retención del IGV |
| `PERCEPTION_AGENT` | +10 | Agente de percepción (solo si no es de retención) |
| `DOMICILE_FOUND` | +10 | Condición `HABIDO` |
| `DOMICILE_UNVERIFIED` | −10 | Condición `PENDIENTE` o `POR VERIFICAR` |
| `COMPANY` | +5 | RUC 20 (persona jurídica) |
| `INDIVIDUAL` | −5 | RUC 10 (persona natural con negocio) |
| `NAME_MATCHES` | +5 | La razón social de la factura coincide con la de SUNAT (similitud ≥ 0,85) |
| `NAME_MISMATCH` | −15 | No coincide |
| `TERM_UP_TO_30_DAYS` | +10 | Vence en 30 días o menos |
| `TERM_31_TO_60_DAYS` | +5 | Vence en 31 a 60 días |
| `TERM_61_TO_90_DAYS` | 0 | Vence en 61 a 90 días |
| `TERM_OVER_90_DAYS` | −10 | Vence en más de 90 días |
| `COACTIVE_DEBT` | −20 | Figura en la lista de SUNAT de mayor deuda en cobranza coactiva |
| `OECE_DISQUALIFIED` | −15 | Tiene una inhabilitación de OECE vigente hoy (sin fecha de fin, o que termina hoy o después) |
| `OECE_UNPAID_FINE` | −10 | Tiene multas de OECE en la lista |
| `ENVIRONMENTAL_OFFENDER` | −5 | Figura en el registro de infractores de OEFA |
| `CREDIT_RATING_NORMAL` | 0 | Central simulada: Normal |
| `CREDIT_RATING_CPP` | −10 | Central simulada: CPP |
| `CREDIT_RATING_DEFICIENT` | −20 | Central simulada: Deficiente |
| `CREDIT_RATING_DOUBTFUL` | −30 | Central simulada: Dudoso |
| `CREDIT_RATING_LOSS` | −40 | Central simulada: Pérdida (nunca rechaza) |
| `SOURCE_UNAVAILABLE` | 0 | Una lista de sanciones que nunca se cargó: queda la constancia |
| `NEGATIVE_NEWS_SERIOUS` | −20 | Al menos una noticia de fraude, quiebra o corrupción |
| `NEGATIVE_NEWS_MODERATE` | −10 | Al menos una de juicios por impago, ambiental u otra |
| `NEWS_UNAVAILABLE` | 0 | La búsqueda de noticias falló: queda la constancia |
| `NEWS_NOT_SCREENED` | 0 | La búsqueda está apagada o no hay `OPENAI_API_KEY` |

Para comparar nombres se pasan a mayúsculas y se quitan tildes, puntuación y la forma societaria (S.A.C., S.R.L., E.I.R.L., «Sociedad Anónima Cerrada»…). Así «Pagador S.A.C.» y «PAGADOR SOCIEDAD ANONIMA CERRADA» coinciden.

## 3. Nota

| Puntaje | Nota |
|---|---|
| 75 o más | A |
| 55 a 74 | B |
| Menos de 55 | C |

Ejemplos:

- Empresa habida, nombre que coincide, 45 días: 40 + 10 + 5 + 5 + 5 = **65 → B**.
- Lo mismo, pero agente de retención: **85 → A**.
- Nombre que no coincide: **45 → C**.
- Empresa habida típica con calificación CPP: **55 → B**; si además tiene deuda coactiva: **35 → C**.

## Las noticias las busca una IA, pero no pone la nota

`OpenAINewsScreener` (`assessments/infrastructure/news.py`) hace una sola llamada a la Responses API de OpenAI con `gpt-6-luna`, su herramienta `web_search` (hasta 5 búsquedas, ubicación Perú) y una respuesta con esquema fijo: una lista de hallazgos con categoría, gravedad, titular, URL, fecha y resumen. Costo verificado el 15 oct 2026: $0,10 / $0,50 por millón de tokens y $10 por 1.000 búsquedas, o sea unos **$0,05 por pagador**.

- **Las instrucciones** tratan cada página como dato, nunca como órdenes, y piden solo noticias claramente sobre esa empresa (mismo RUC o misma razón social) de los últimos 5 años.
- **Después se valida**: un hallazgo cuya URL no está entre las páginas que la búsqueda consultó de verdad se descarta; así un enlace inventado nunca llega a la nota. También se descartan las páginas de registros que ya se leen aparte (SUNAT, OECE, OEFA, datos abiertos), para no contar dos veces lo mismo. Una respuesta que no cumple el esquema cuenta como «no respondió».
- **La gravedad no la decide la IA**: sale de la categoría (fraude, quiebra y corrupción son graves; lo demás, moderado). En las primeras pruebas reales la IA marcaba como moderado un juicio por tráfico de influencias.
- **Nunca rechaza y nunca pasa de −30**: una búsqueda automática puede confundir homónimos o leer mal una página.
- **Caché de 7 días por RUC** (tabla `news_screenings`): el mismo pagador no se vuelve a buscar en ese plazo, haya encontrado algo o no.
- **Sin clave** (`OPENAI_API_KEY`) o con `NEWS_ENABLED=false`, el paso se salta y queda `NEWS_NOT_SCREENED`.

## La central de riesgos es SIMULADA

Vankoo no tiene contrato con una central (Equifax/Infocorp, Sentinel…). Además, una plataforma de financiamiento participativo la supervisa la SMV y no tiene acceso directo al reporte consolidado de la SBS.

`SimulatedCreditBureau` (`assessments/infrastructure/credit_bureau.py`) inventa una calificación SBS a partir del SHA-256 del RUC, siempre la misma para el mismo RUC: Normal 70 %, CPP 12 %, Deficiente 8 %, Dudoso 6 %, Pérdida 4 %. El detalle de su factor dice «(simulado)», y **solo resta puntos**: nunca rechaza una factura, porque el dato es inventado.

Para usar una central real se escribe otro adaptador del puerto `CreditBureau` y se elige en `build_credit_bureau()`. Con `CREDIT_BUREAU_ENABLED=false` la calificación sale de la nota.

## Sin padrón

Mientras el padrón no se haya cargado nunca, cada subasta sale **C** con el factor `REGISTRY_UNAVAILABLE`. Nunca se rechaza por falta de datos.

## Cambiar las reglas

Se escribe una política nueva (o una versión nueva, `points-v4`) en `assessments/domain/services.py`, con sus tests, y se devuelve en `build_grading_policy()`. Las evaluaciones ya emitidas conservan su `grading_policy`.
