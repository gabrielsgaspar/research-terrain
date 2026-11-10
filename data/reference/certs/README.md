# Pinned intermediate certificates

Public CA certificates that a download server fails to send. They are not
secrets. Each file is the base64 of the certificate's DER bytes, so no PEM
marker appears in the repository: the workflows refuse any text that
contains one. Code loads a file with
`ssl.SSLContext.load_verify_locations(cadata=base64.b64decode(...))`, on top of
the system trust store, after checking its SHA-256. The chain must still end
at a root the system trusts: an intermediate here is never a trust anchor
(the partial-chain flag stays off).

| File | Certificate | Issuer | Valid until | SHA-256 of the DER | Needed by |
| --- | --- | --- | --- | --- | --- |
| `rnp_icpedu_gr46_ov_tls_ca_2025.der.b64` | RNP ICPEdu GR46 OV TLS CA 2025 | GlobalSign Root R46 | 2030-11-19 | `e10747d4da7bab09cba9952f019d3534cb9fba070bf13d8791b1699cd2ff59dd` | `download.inep.gov.br` (INEP), which does not send it |

Downloaded on 2026-11-10 from the issuer's address in INEP's certificate
(`http://secure.globalsign.com/cacert/rnpicpedugr46ovtlsca2025.crt`). With it
added to the system store, a request to
`https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_2024.zip`
verified and returned HTTP 200; without it, verification failed ("unable to
get local issuer certificate").
