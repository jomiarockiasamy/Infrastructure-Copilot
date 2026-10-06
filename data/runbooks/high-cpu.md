---
service: checkout-api
environment: prod
host: checkout-api-01
failure_symptom: high cpu
---

## Symptoms
checkout-api-01 in prod is pegged at high cpu. The storefront process sits near 100 percent CPU during price calculations and promo math. Request latency climbs, but memory and disk look normal. Checkout on-call Blake Okonkwo gets paged when the host stays above 85 percent for five minutes.

## Likely cause
A recent price-rule change made the checkout-api recompute every cart line in a tight loop. The high cpu is compute bound on checkout-api-01 in prod, not a database wait. Flame graphs show the promo engine on the stack.

## Steps
Capture a five-second profile on checkout-api-01 and confirm the promo engine is hot. Roll back the price-rule change immediately if the error budget is burning. Scale the checkout-api deployment by two replicas only after the rollback, then watch CPU fall under 60 percent. Tell Blake Okonkwo on Checkout if the host is still pegged. Do not raise database pool size for a high cpu incident.

## Steps
Capture a five-second profile on checkout-api-01 and confirm the promo engine is hot. Roll back the price-rule change promptly if the error budget is burning. Scale the checkout-api deployment by two replicas only after the rollback, then watch CPU fall under 60 percent. Tell Blake Okonkwo on Checkout if the host is still pegged. Do not raise database pool size for a high cpu incident.
