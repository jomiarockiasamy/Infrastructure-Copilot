---
service: checkout-api
environment: prod
host: checkout-api-01
failure_symptom: network latency
---

## Symptoms
checkout-api-01 in prod shows network latency on downstream calls. The storefront itself is idle, but dependency spans to inventory are sluggish, with round trip times several times the baseline. Packet loss is low. Checkout on-call Blake Okonkwo is paged for slow downstream calls.

## Likely cause
A congested path between checkout-api-01 and the inventory subnet added queueing delay. This network latency incident is in prod and is not high cpu on the storefront. Traceroute shows extra delay at one hop.

## Steps
Compare dependency latency from checkout-api-01 to inventory against the next healthy zone. Shift checkout traffic off the congested path. Confirm sluggish downstream calls return to baseline. Update Blake Okonkwo on Checkout if the hop stays slow. Do not scale checkout-api for a network latency problem.
