# Contrato `green-certifications` v1

Lo publica `vankoo-risk-service` y lo consume `vankoo-profile-service`. Es la respuesta a cada `SustainabilityCertificateSubmitted` de Profile: si el certificado que subió la MYPE la hace verde, y por qué.

| | |
|---|---|
| Tópico | `risk.green-certifications.v1` |
| Clave | `companyId`: los mensajes de una empresa van a la misma partición |
| Formato | JSON UTF-8, un sobre con `data` |
| Entrega | Al menos una vez, desde un outbox (`outbox_messages`). Hay que deduplicar por `eventId` |

## `GreenCertificationIssued`

Ejemplo completo en [`green-certification-issued.json`](green-certification-issued.json).

| Campo | Tipo | Qué es |
|---|---|---|
| `eventId` | UUID | Identificador del mensaje |
| `eventType` | `"GreenCertificationIssued"` | |
| `schemaVersion` | `1` | Una versión distinta no se procesa |
| `occurredAt` | instante ISO-8601 UTC | Cuándo se decidió |
| `data.certificationId` | texto | Id de la decisión en risk (`green-…`); Investment lo guarda en la subasta |
| `data.submissionId` | texto | El `submissionId` que mandó Profile. **Si ya no es la subida vigente, el mensaje se ignora** |
| `data.companyId` | texto | Perfil de la MYPE |
| `data.mypeUserId` | texto | Cuenta de IAM de la MYPE (el `mypeId` de sus subastas) |
| `data.decision` | `GREEN` \| `NOT_GREEN` | |
| `data.standard` | `ISO_14001` \| `ISO_50001` \| `null` | La norma, si es una de las aceptadas |
| `data.issuer` | texto \| `null` | El organismo certificador, tal como lo leyó la IA |
| `data.validUntil` | fecha `YYYY-MM-DD` \| `null` | Vencimiento |
| `data.criteria[]` | `{code, passed, detail}` | Cada regla de `green-v1` y lo que encontró (`detail` en español) |
| `data.reasonCodes[]` | texto | Los `code` que fallaron; vacío si es `GREEN` |
| `data.decidedAt` | instante ISO-8601 UTC | |
| `data.rulesVersion` | texto | `green-v1` |

Un documento ilegible solo trae `CERTIFICATE_READABLE` en `criteria`, porque las demás reglas necesitan sus datos. Las reglas están en [`GREEN_RULES.md`](../../../GREEN_RULES.md).

## Lo que risk lee de Profile

Del tópico `vankoo.profile.events` (de Profile, sin versionar) solo procesa `SustainabilityCertificateSubmitted` con `schemaVersion` 1; los demás eventos los salta. Campos que usa: `eventId`, `occurredAt`, `submissionId`, `companyId`, `userId`, `rucNumber`, `businessName`, `objectKey` y `contentType`. Ejemplo en [`tests/contracts/profile-events/v1`](../../../../tests/contracts/profile-events/v1). El contrato es de Profile y vive en su repositorio.
