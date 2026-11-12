# Contrato `company-verifications` v1

Lo publica `vankoo-risk-service` y lo consume `vankoo-profile-service`. Es la respuesta a cada `CompanyVerificationRequested` de Profile: si la MYPE es quien dice ser (su KYC), y por qué. **Risk recomienda y Profile decide**: el estado KYC de la MYPE lo guarda y lo cambia Profile.

| | |
|---|---|
| Tópico | `risk.company-verifications.v1` |
| Clave | `companyId`: los mensajes de una empresa van a la misma partición |
| Formato | JSON UTF-8, un sobre con `data` |
| Entrega | Al menos una vez, desde un outbox (`outbox_messages`). Hay que deduplicar por `eventId` |

## `CompanyVerificationIssued`

Ejemplo completo en [`company-verification-issued.json`](company-verification-issued.json).

| Campo | Tipo | Qué es |
|---|---|---|
| `eventId` | UUID | Identificador del mensaje |
| `eventType` | `"CompanyVerificationIssued"` | |
| `schemaVersion` | `1` | Una versión distinta no se procesa |
| `occurredAt` | instante ISO-8601 UTC | Cuándo se decidió |
| `data.verificationId` | texto | Id de la decisión en risk (`kyc-…`) |
| `data.requestId` | texto | El `requestId` que mandó Profile. **Si ya no es la solicitud vigente, el mensaje se ignora** |
| `data.companyId` | texto | Perfil de la MYPE |
| `data.userId` | texto | Cuenta de IAM de la MYPE |
| `data.decision` | `VERIFIED` \| `REJECTED` \| `CORRECTION_REQUIRED` | `CORRECTION_REQUIRED` no es un rechazo: hay que corregir un campo y reenviar, sin espera |
| `data.checks[]` | `{code, passed, detail}` | Las ocho reglas de `kyc-v1`, siempre en el mismo orden (`detail` en español) |
| `data.reasonCodes[]` | texto | Los `code` que fallaron; vacío si es `VERIFIED` |
| `data.fieldErrors[]` | `{field, code}` | Solo con `CORRECTION_REQUIRED`: `rucNumber`/`RUC_NOT_FOUND` o `businessName`/`NAME_MISMATCH` |
| `data.evidence[]` | `{code, detail}` | Sanciones que no rechazan: `COACTIVE_DEBT`, `OECE_SANCTION`, `ENVIRONMENTAL_OFFENDER` |
| `data.demo` | booleano | `true` si la ficha la firmó la CA de demostración de Vankoo y no SUNAT. **Profile y la web deben mostrarlo aparte («Verificado (demo)»)** |
| `data.decidedAt` | instante ISO-8601 UTC | |
| `data.rulesVersion` | texto | `kyc-v1` |

Las reglas están en [`KYC_RULES.md`](../../../KYC_RULES.md).

## Lo que risk lee de Profile

Del tópico `vankoo.profile.events` solo procesa `CompanyVerificationRequested` con `schemaVersion` 1; los demás eventos los salta (en su propio grupo de consumidores, `risk-profile-verification-v1`). Campos que usa: `eventId`, `occurredAt`, `requestId`, `companyId`, `userId`, `rucNumber`, `businessName` y `rucDocumentKey` (`companies/{companyId}/ruc/{uuid}.pdf`). Ejemplo en [`tests/contracts/profile-events/v1`](../../../../tests/contracts/profile-events/v1). El contrato es de Profile y vive en su repositorio.
