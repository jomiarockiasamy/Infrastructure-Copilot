---
service: redis
environment: prod
host: redis-01
failure_symptom: cache eviction
---

## Symptoms
redis-01 in prod is evicting keys. Checkout cache misses jumped and the cache node reports maxmemory reached. The eviction policy is allkeys-lru. Caching on-call Frankie Alvarez owns redis.

## Likely cause
A new cache prefix stored full cart documents without a TTL, so redis-01 filled and started dropping hot keys. This cache eviction incident is in prod. The checkout database is healthy. Memory fragmentation is not the driver.

## Steps
Run INFO memory on redis-01 and list the largest prefixes. Delete the unbounded prefix and set a TTL on new cart keys. Confirm evictions stop and checkout cache misses fall. Page Frankie Alvarez on Caching if used memory stays at maxmemory. Do not flush the entire instance.
