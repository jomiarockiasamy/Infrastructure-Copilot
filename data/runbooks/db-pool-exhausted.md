---
service: payments-db
environment: prod
host: payments-db-01
failure_symptom: connection pool exhausted
---

## Symptoms
The payments db in prod is timing out. checkout cannot charge cards because payments-db-01 refuses new db sessions. Application logs say the connection pool is exhausted and waits exceed the timeout. CPU and disk on the database host are healthy. Payments Platform on-call Avery Chen is paged.

## Likely cause
A leaked transaction in the payments service held pool connections until the pool was exhausted. The payments database itself is accepting local connections. The timeout is at the application pool on the path to payments-db-01 in prod, not a disk full event.

## Steps
Check pool in-use versus max on the payments service. Find sessions idle in transaction on payments-db-01 and cancel only those leaked backends. Restart the payments connection pool so new checkouts can borrow a session. Ask Avery Chen on Payments Platform to review the settlement job if the pool fills again. Do not raise max connections above the database limit.
