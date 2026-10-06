# Evaluation results

## Precision@3

| Setup | Precision@3 |
| --- | --- |
| Plain vector search | 0.6444 |
| Rewriting only | 0.6444 |
| Rewriting + metadata filters | 0.6444 |

Questions: 30. Rewrite fell back to the raw query with no filters on 30 of 30 questions.

## Latency

### Retrieval stage

| Mode | Samples | Median (ms) | P95 (ms) |
| --- | --- | --- | --- |
| Cache off | 48 | 72.87 | 90.64 |
| Cache on, warm | 48 | 0.01 | 0.01 |

Median reduction, warm versus cache off: 99.99% ((72.87 - 0.01) / 72.87).
Retrieval stage only: embedding plus Chroma, or a cache read. Rewrite is not included.

### End to end, including rewrite

| Mode | Samples | Median (ms) | P95 (ms) |
| --- | --- | --- | --- |
| Cache off | 48 | 83.76 | 161.00 |
| Cache on, warm | 48 | 0.01 | 0.02 |

Median reduction, warm versus cache off: 99.98% ((83.76 - 0.01) / 83.76).
Cache-off rewrite did not reach an LLM (48 fallbacks). This timing is the fallback plus retrieval, not a live model call. A warm hit skips both the rewrite call and the Chroma query.
