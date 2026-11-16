# Reglas del KYC de la MYPE (`kyc-v1`)

Una MYPE queda **verificada** cuando la ficha RUC que subió a su perfil es auténtica, reciente y suya, y SUNAT la muestra activa, habida y fuera de la lista de empresas sin capacidad operativa. **Risk aporta la evidencia y una recomendación; Profile decide** el estado KYC y lo guarda.

## Cómo se decide

1. La MYPE completa su perfil en la web y sube su **ficha RUC** (el PDF que descarga de SUNAT Operaciones en Línea). Profile publica `CompanyVerificationRequested` en `vankoo.profile.events` y deja el perfil «En revisión».
2. Risk lo lee en su propio grupo de consumidores (`KYC_PROFILE_GROUP_ID`) y consulta sus copias del **padrón reducido** y de la **lista SSCO**. Si el padrón o la SSCO nunca se cargaron, **no decide**: reintenta el mensaje hasta que estén.
3. Descarga la ficha del bucket de Profile y **verifica su firma digital sin salir a internet** (ver abajo). Lee el texto con pypdf: RUC, nombre, estado, condición del domicilio y fecha de emisión. Sin IA.
4. Las reglas de abajo deciden. Cada una se guarda con su resultado y su detalle en `company_verifications`.
5. La decisión vuelve a Profile por Kafka (`risk.company-verifications.v1`, contrato en [contracts/company-verifications/v1](contracts/company-verifications/v1/README.md)).

## Cómo se sabe que la ficha es de SUNAT sin entrar a su web

SUNAT firma cada ficha RUC con una firma digital incrustada en el PDF (`adbe.pkcs7.detached`, SHA-256), la misma que valida su página «Validación de documentos con Firma Digital». Esa firma es un sello criptográfico sobre **todos los bytes del archivo**: si alguien cambia una letra, la firma deja de cuadrar. Risk la comprueba con **pyHanko**:

| Comprobación | Qué asegura |
|---|---|
| La firma cuadra con el contenido (`intact` y `valid`) | Nadie tocó la ficha después de firmarla |
| La firma cubre **todo** el archivo (`ENTIRE_FILE`) | No se le añadió nada después (una «actualización incremental» con otro texto) |
| El certificado del firmante encadena hasta la raíz **Llama.pe Root CA**, fijada en el repositorio | La firmó alguien con un certificado de una entidad de certificación peruana, no uno hecho en casa |
| La organización del firmante es exactamente `SUPERINTENDENCIA NACIONAL DE ADUANAS Y DE ADMINISTRACION TRIBUTARIA - SUNAT` | De todos los certificados que emite Llama.pe, este es el de SUNAT |

Los certificados fijados son públicos y están en [`verification/infrastructure/trust/`](../verification/infrastructure/trust/):

| Archivo | Sujeto | Vigencia | SHA-256 |
|---|---|---|---|
| `llama-pe-root-ca.pem` | `CN=Llama.pe Root CA, O=LLAMA.PE, C=PE` (raíz) | 2018-07-18 → 2038-07-13 | `22:8C:A8:4D:00:68:7D:20:DF:E5:43:4A:7A:C9:82:E7:55:32:A8:14:66:01:89:6E:DC:D9:14:6E:54:A2:89:FE` |
| `llama-pe-sha256-standard-ca.pem` | `CN=Llama.pe SHA256 Standard CA` (intermedia) | 2018-07-18 → 2038-07-13 | `04:12:EB:96:2C:BE:52:AA:80:D2:62:B4:55:5D:3C:74:07:FF:ED:A2:8F:FD:0C:7D:F3:68:07:B4:D3:0A:6C:72` |

Se sacaron de la firma de una ficha real (29 oct 2026). El firmante era «AGENTE AUTOMATIZADO» de SUNAT, vigente del 2024-08-09 al 2027-08-09.

**Lo que no se comprueba**, a propósito:
- **Revocación** (OCSP o CRL): haría falta salir a internet en cada ficha.
- **El sello de tiempo** que trae la firma: es de una TSA cuya raíz no está fijada. En su lugar, la regla `RUC_DOCUMENT_RECENT` usa la fecha impresa, que también está firmada.
- **Que la raíz de Llama.pe coincida con la lista de confianza de INDECOPI.** Queda pendiente cotejar la huella de arriba con la TSL publicada.

## Las reglas

Se hacen siempre las ocho, en este orden.

| Código | Pasa si | Si falla |
|---|---|---|
| `TAXPAYER_FOUND` | El RUC está en el padrón, **o** no lo está pero la ficha firmada por SUNAT es de ese RUC (el padrón tarda en incluir a los contribuyentes nuevos). En ese caso el estado y la condición se toman de la ficha, y el detalle lo dice | `CORRECTION_REQUIRED` con `rucNumber`/`RUC_NOT_FOUND`, sin espera: lo más probable es un RUC mal escrito, y las demás reglas se hicieron contra el contribuyente equivocado |
| `RUC_DOCUMENT_SIGNED` | La firma pasa las comprobaciones de arriba (o es la de demostración, si está activada) | Rechazo. También si el archivo no existe, no es un PDF o pasa de `KYC_MAX_BYTES` |
| `RUC_DOCUMENT_RECENT` | La «Fecha:» de la ficha tiene **30 días o menos** en Lima y no es futura | Rechazo |
| `RUC_DOCUMENT_MATCHES` | El RUC de la ficha es el declarado | Rechazo |
| `NAME_MATCHES` | El nombre de la ficha coincide con el del padrón (o con el de la ficha, si no está en el padrón), y el nombre declarado también. Se comparan como en `green-v1`: mayúsculas, sin tildes, sin puntuación y sin la forma societaria final | Si solo difiere el nombre declarado y todo lo demás pasa: `CORRECTION_REQUIRED` con `businessName`/`NAME_MISMATCH`. Si la ficha es de otro nombre: rechazo |
| `TAXPAYER_ACTIVE` | El estado es `ACTIVO` (del padrón; o de la ficha si no está en él) | Rechazo |
| `DOMICILE_FOUND` | La condición del domicilio es `HABIDO` (ídem) | Rechazo |
| `NOT_SHELL_COMPANY` | El RUC no está en la lista SSCO de SUNAT | Rechazo |

**Solo la SSCO rechaza** de las listas de sanciones. La deuda coactiva de SUNAT, las sanciones vigentes del OECE y el registro de infractores de OEFA se guardan como `evidence` y viajan a Profile, sin cambiar la decisión.

Con un rechazo, Profile aplica la espera para reenviar (24 h, 72 h y luego 7 días).

## Cómo se lee la ficha

pypdf devuelve las líneas en el orden en que el PDF las dibuja. En la ficha de un RUC 10 (persona natural con negocio) aparecen así:

| Dato | Dónde |
|---|---|
| RUC | La primera línea de solo 11 dígitos después del encabezado «Reporte de Ficha RUC» |
| Nombre | Las líneas entre ese encabezado y el RUC, unidas (un nombre largo ocupa dos) |
| Fecha de emisión | «Fecha: dd/mm/aaaa» |
| Estado | «Estado del Contribuyente …» |
| Condición | «Condición del Domicilio Fiscal …» |

**Sin comprobar:** la ficha de un RUC 20 (persona jurídica). Se espera el mismo encabezado; si cambia, hay que ajustar `verification/infrastructure/inspector.py`. Si SUNAT cambia de entidad de certificación o de formato, el KYC rechaza todas las fichas hasta actualizar `trust/` y el parser.

## Demostraciones: fichas firmadas por Vankoo

> **Parche temporal.** Para exponer sin usar la ficha de una persona real. Quitarlo cuando acaben las demos: `verification/infrastructure/demo.py`, `verification/interfaces/cli.py`, `verification/__main__.py` y `KYC_DEMO_CA_PATH`.

```bash
uv run python -m verification demo-ca
uv run python -m verification demo-ficha --ruc 20601234567 --name "TEXTILES ANDINOS S.A.C." --out demo-kyc/ficha.pdf
```

- `demo-ca` crea una CA local en `demo-kyc/` (fuera de git) e imprime la ruta para `KYC_DEMO_CA_PATH`.
- `demo-ficha` escribe una ficha con el mismo formato, con «DOCUMENTO DE DEMOSTRACIÓN — NO VÁLIDO» arriba y abajo, firmada por esa CA. Con `--unsigned` sale sin firma, con `--days-old 45` sale vieja, y `--status`/`--condition` cambian lo que imprime.
- **Risk solo acepta esa CA si `KYC_DEMO_CA_PATH` apunta a ella**, y lo avisa en el log al arrancar. Sin la variable (por defecto), solo vale la firma de SUNAT.
- Una decisión sobre una ficha de demo lleva `demo: true` y el detalle «Firma de demostración de Vankoo, no de SUNAT». Profile y la web la muestran como **«Verificado (demo)»**, separado de «Verificado».

Nunca definir `KYC_DEMO_CA_PATH` en producción.
