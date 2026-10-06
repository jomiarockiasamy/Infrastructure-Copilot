---
service: edge-proxy
environment: prod
host: edge-01
failure_symptom: upstream 5xx
---

## Symptoms
edge-01 in prod is returning upstream 5xx for checkout. The public proxy shows server errors while the checkout health check flaps. Client tls handshakes succeed, so this is not an expired certificate. Edge Networking on-call Devon Patel owns the load balancer path.

## Likely cause
Two checkout upstreams were marked up while they were still booting, so edge-01 forwarded traffic and received connection resets. The upstream 5xx spike is in prod. The certificate on the proxy is valid.

## Steps
Drain the booting upstreams on edge-01 and keep only ready checkout targets. Watch the 5xx rate fall and the health checks stay green. Return the drained targets after they pass readiness. Contact Devon Patel if server errors continue. Do not disable health checks.
