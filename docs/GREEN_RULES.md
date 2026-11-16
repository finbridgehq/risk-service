# Reglas del factoring verde (`green-v1`)

Una subasta es **verde** cuando su MYPE es verde el día en que se evalúa. Una MYPE es verde cuando el último certificado que subió a su perfil pasa todas las reglas de esta página. Cubre US10 (distintivo `Factoring Verde` con los criterios que lo sustentan) y deja listo US11 (el marketplace filtra por `greenCertified`).

## Cómo se decide

1. La MYPE sube su certificado a Profile (PDF, JPG o PNG). Profile publica `SustainabilityCertificateSubmitted` en `vankoo.profile.events`.
2. Risk lo descarga del bucket de Profile y se lo pasa a **OpenAI** (`GREEN_MODEL`, `gpt-6-luna` por defecto), que **solo transcribe** lo que está impreso: norma, organismo certificador, titular, RUC, emisión, vencimiento y alcance. El PDF viaja como `input_file` y la imagen como `input_image`, los dos en base64. La IA no decide nada.
3. Las reglas de abajo deciden con esos datos y con las copias locales de SUNAT y OEFA. Cada regla se guarda con su resultado y su detalle en `green_certifications`.
4. La decisión vuelve a Profile por Kafka (`risk.green-certifications.v1`, contrato en [contracts/green-certifications/v1](contracts/green-certifications/v1/README.md)) y la MYPE la ve en su perfil.
5. En cada `AuctionCreated` **elegible**, risk mira el último certificado decidido de esa MYPE y repite dos reglas con la fecha del día: la vigencia y OEFA. Si pasa, le manda a Investment el certificado y sus criterios (`greenCertification`), y la subasta queda verde.

## Las reglas

Es verde solo si pasan las cinco.

| Código | Pasa si | Si falla |
|---|---|---|
| `CERTIFICATE_READABLE` | El archivo se pudo descargar y la IA lo reconoce como el certificado de un sistema de gestión | Archivo inexistente, de más de `GREEN_MAX_BYTES`, de otro tipo, o una respuesta de la IA que no valida. Las demás reglas no se evalúan, porque necesitan los datos del documento |
| `ACCEPTED_STANDARD` | La norma es **ISO 14001** (gestión ambiental) o **ISO 50001** (gestión de la energía) | Otra norma (ISO 9001, por ejemplo) o ninguna legible |
| `IN_FORCE` | Tiene fecha de vencimiento, no está vencido hoy (en Lima) y su emisión no es futura | Sin fecha de vencimiento impresa no hay verde |
| `HOLDER_MATCHES_SUNAT` | El titular coincide con la razón social que tiene SUNAT para el RUC del perfil, y, si el certificado imprime un RUC, es ese mismo | Se comparan en mayúsculas, sin tildes, sin puntuación y sin la forma societaria final (S.A.C., S.A., S.R.L., E.I.R.L. o su forma larga). Sin padrón cargado, o con un RUC que no está en él, falla |
| `NOT_ENVIRONMENTAL_OFFENDER` | El RUC no figura en el registro de infractores ambientales de OEFA (`environmental_offenders`) | También falla si ese registro nunca se cargó |

### En cada subasta

| Estado | Cuándo |
|---|---|
| `GREEN` | El último certificado decidido fue verde, sigue vigente hoy y la MYPE no entró en OEFA |
| `NO_CERTIFICATE` | La MYPE nunca subió uno, o ninguno se decidió todavía |
| `NOT_GREEN` | El último certificado no pasó las reglas. **Cuenta el último**, aunque uno anterior fuera verde, para que la subasta diga lo mismo que el perfil |
| `EXPIRED` | Era verde, pero venció |
| `ENVIRONMENTAL_OFFENDER` | Era verde, pero la MYPE aparece ahora en OEFA |
| `NOT_CHECKED` | La factura no es elegible: el verde no importa |

El estado se guarda en `risk_assessments.green_status` (el motivo, cuando no es verde, como pide el escenario 2 de US10) y el certificado enviado en `green_certificate`. `GET /api/v1/risk-assessments/{auctionId}` muestra los dos.

## Lo que esto NO comprueba

- **Autenticidad.** La IA comprueba que el certificado sea coherente con SUNAT y OEFA, no que sea verdadero. Un certificado falso bien hecho pasa. En producción haría falta consultar al organismo certificador (o su registro público) y verificar que esté acreditado (INACAL en Perú o un miembro del IAF).
- **El alcance.** Se guarda, pero no se exige que cubra la actividad de la factura.
- **Otros sellos** (Huella de Carbono Perú, B Corp…). Quedaron fuera porque no traen una fecha de vencimiento clara.

## Defensas

- La IA tiene instrucciones de tratar el documento como **dato, nunca como instrucción**. Un texto incrustado no cambia la decisión: aunque la IA lo obedeciera y dijera que es ISO 14001, las reglas siguen pidiendo vigencia, titular y OEFA.
- La clave del archivo debe estar dentro de `companies/{companyId}/sustainability/`, con la extensión de su tipo, y se descarga desde `GREEN_DOCUMENTS_BASE_URL`. Nunca desde una URL que llegue en el evento, así que nadie puede hacer que risk descargue otra cosa.
- Se comprueba la firma del archivo (`%PDF-`, JPEG, PNG), no solo su extensión.
- Si OpenAI no responde, rechaza la clave o limita el uso, no se decide nada: el mensaje se reintenta, en vez de marcar como ilegibles todos los certificados mientras dure el problema.

## Sin clave

Sin `OPENAI_API_KEY`, o con `GREEN_ENABLED=false`, las subidas **quedan sin decidir**: el evento se registra como procesado y Profile sigue mostrando «en revisión». Las subastas salen `NO_CERTIFICATE`.

## Coste

Una llamada por certificado, sin búsqueda web. `gpt-6-luna` cuesta $0,10 por millón de tokens de entrada y $0,50 por millón de salida (verificado el 16 oct 2026 en la ficha del modelo). Un PDF entra como texto más una imagen por página, así que el coste depende del documento. Cada lectura registra en el log sus tokens de entrada y de salida.
