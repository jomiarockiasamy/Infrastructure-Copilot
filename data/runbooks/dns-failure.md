---
service: dns-resolver
environment: prod
host: dns-01
failure_symptom: dns failure
---

## Symptoms
dns-01 in prod is failing lookups. Applications receive NXDOMAIN or SERVFAIL for internal service names such as checkout.internal. Pods cannot resolve names even though the network path to the resolver is open. Edge Networking on-call Devon Patel owns dns-resolver.

## Likely cause
The prod resolver on dns-01 loaded a stale zone after a bad serial. The dns failure is limited to internal names. Public recursion still works. A typo in the zone file dropped the checkout.internal record.

## Steps
Query dns-01 directly with dig checkout.internal @dns-01. If the answer is NXDOMAIN, restore the last known-good zone file and bump the serial. Reload the resolver and confirm pods can resolve names again. Page Devon Patel on Edge Networking if the zone will not load. Do not restart application pods until dig succeeds.

## Steps
Query dns-01 directly with dig checkout.internal @dns-01. If the answer is NXDOMAIN, restore the last known-good zone file and bump the serial. Reload the resolver and confirm pods can resolve names again. Page Devon Patel on Edge Networking if the zone will not load. Do not restart application pods until dig succeeds.
