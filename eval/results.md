# Router eval results

90 cases from `eval/dataset.jsonl`, run on 2026-11-19.

| model | exact | route | project | session | noisy dictation | p50 | p95 | cost / 1000 requests | errors |
|---|---|---|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | 97% | 100% | 97% | 98% | 100% | 2559 ms | 20015 ms | $0.439 | 0 |
| gemini-flash-lite-latest | 94% | 99% | 97% | 97% | 100% | 1585 ms | 22412 ms | - | 1 |

- **exact**: route, project and session all right.
- **project / session**: scored only on cases where the right answer is a task.
- **noisy dictation**: exact score on the `n*` cases, where speech-to-text mangled technical words.
- Latency is measured from this PC, including network; errors are excluded from latency and cost.
- p95 includes waiting out the API's `503 overloaded` replies (retried after 10 s, 20 s, 30 s);
  p50 is closer to a normal call. In real use the server tries the next model instead of waiting.
- A model with errors could not be scored on those cases (the API kept answering 503).
- Cost uses token counts reported by the API and prices in `eval/prices.json`.
