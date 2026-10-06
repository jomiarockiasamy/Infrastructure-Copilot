---
service: worker
environment: prod
host: worker-01
failure_symptom: crashloop
---

## Symptoms
worker-01 in prod is in a crashloop. The async job pod starts, exits in a few seconds, and Kubernetes restarts it. Logs show a missing config key from the mounted file. Restarts climb and the job queue stops draining. Async Jobs on-call Gray Ibarra owns the worker service.

## Likely cause
A deploy mounted an empty config file into the worker container, so the process exits on startup. The crashloop on worker-01 in prod is a bad config mount, not an out-of-memory kill. The previous image was healthy.

## Steps
Read the last crash log on worker-01 and confirm the missing config key. Roll the worker deployment back to the previous image and restore the config map. Watch the restart count return to zero and the queue start draining. Contact Gray Ibarra on Async Jobs if the pod still crashloops. Do not delete the pod volume claims.
