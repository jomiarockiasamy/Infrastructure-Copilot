---
service: auth-service
environment: prod
host: auth-01
failure_symptom: certificate mismatch
---

## Symptoms
auth-01 in prod presents a certificate whose name does not match the hostname. Login clients fail tls because the cert name is wrong, even though the certificate date is still in the future. Identity on-call Casey Nguyen owns auth-service.

## Likely cause
A certificate issued for auth.staging.internal was installed on the prod host auth-01. The certificate mismatch is a name error, not an expired tls certificate. The private key matches the certificate.

## Steps
Read the certificate subject on auth-01 and compare it to the prod hostname. Install the prod certificate that lists auth-01 and reload auth-service. Confirm clients no longer report that the cert name is wrong. Tell Casey Nguyen on Identity if the prod secret is absent. Do not add a client-side name override.
