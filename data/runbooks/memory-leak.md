---
service: billing-api
environment: prod
host: billing-01
failure_symptom: memory leak
---

## Symptoms
billing-01 in prod memory keeps growing and never returns to the heap baseline. The invoice api RSS climbs overnight until the process is near the cgroup limit. CPU stays moderate. Billing on-call Harper Singh sees the memory leak alert.

## Likely cause
The invoice renderer caches every PDF byte in a process-global map and never evicts it. The memory leak is in billing-api on billing-01 in prod. Restarting frees memory only until the next invoice batch.

## Steps
Take a heap snapshot on billing-01 and confirm the PDF cache dominates. Roll forward the build that bounds the cache, or restart billing-api as a short bridge. Watch RSS return toward the baseline after the next batch. Contact Harper Singh on Billing if memory grows again within an hour. Do not raise the cgroup limit as the only fix.
