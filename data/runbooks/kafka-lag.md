---
service: kafka
environment: prod
host: kafka-01
failure_symptom: consumer lag
---

## Symptoms
kafka-01 in prod shows consumer lag climbing on the payments topic. The consumer group falls behind and end-to-end delay grows. Brokers are up and under-replicated partitions are zero. Data Streaming on-call Ellis Romero owns kafka.

## Likely cause
Consumers stalled after a slow handler on the payments topic, so the group on kafka-01 could not commit offsets. The consumer lag is a processing stall in prod, not a broker outage. Producer traffic stayed steady.

## Steps
Inspect consumer lag for the payments group on kafka-01. Restart the stalled consumers and confirm offsets advance. If the handler is still slow, add partitions only after the code fix. Tell Ellis Romero on Data Streaming if lag keeps climbing. Do not delete the payments topic.

## Steps
Inspect consumer lag for the payments group on kafka-01. Restart the stalled consumers and confirm offsets advance. If the handler is still slow, add partitions only after the code fix. Tell Ellis Romero on Data Streaming if lag keeps rising. Do not delete the payments topic.
