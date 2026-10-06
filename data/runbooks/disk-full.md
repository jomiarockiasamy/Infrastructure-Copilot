---
service: payments-db
environment: prod
host: payments-db-01
failure_symptom: disk full
---

## Symptoms
Payments database host payments-db-01 in prod reports disk full. Postgres logs show "No space left on device" while writing WAL segments. Write queries fail and the payments service starts failing card charges. df shows the data volume at 100 percent used. The Payments Platform alert pages on-call Avery Chen. This is an out of disk condition on the payments db, not a slow query.

## Likely cause
The payments-db data volume filled because WAL files and nightly base backups were retained on the same disk as the primary data directory. A bulk settlement job kept transactions open, so the WAL could not be recycled. The disk full incident is on payments-db-01 in prod. Free space must be restored before writes succeed.

## Steps
Confirm the mount with df -h on payments-db-01. Stop new bulk loads. Delete expired WAL archives older than the last successful base backup from the archive directory only. Run a checkpoint after free space returns, then retry a payments write. Escalate to Payments Platform on-call Avery Chen if the volume is still above 90 percent. Do not delete the live pg_wal directory itself. The payments database in prod should accept writes again once the data volume has free blocks.

## Steps
Confirm the mount with df -h on payments-db-01. Stop new bulk loads. Delete expired WAL archives older than the last successful base backup from the archive directory only. Run a checkpoint after free space returns, then retry a payments write. Escalate to Payments Platform on-call Avery Chen if the volume is still above 90 percent. Do not delete the live pg_wal directory itself. The payments database in prod should accept writes again once the data volume has free blocks.
