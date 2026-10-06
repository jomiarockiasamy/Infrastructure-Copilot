---
service: edge-proxy
environment: prod
host: edge-01
failure_symptom: expired tls
---

## Symptoms
edge-01 in prod is serving an expired tls certificate. Browsers show that the certificate date is past, and clients fail the handshake before any HTTP status. The public proxy still listens on 443. Edge Networking on-call Devon Patel owns edge-proxy.

## Likely cause
The certificate for the public hostname expired at midnight and the renewal job did not install the new file on edge-01. This expired tls incident is a date problem, not a hostname mismatch. The private key on disk is still valid.

## Steps
Check the notAfter date with openssl on edge-01. Install the renewed certificate and reload the proxy process. Confirm a fresh handshake from outside the network. Tell Devon Patel if the renewed file is missing from the secret store. Do not disable tls verification on clients.
