# Router eval results

20 cases from `eval/holdout.jsonl`, run on 2026-11-19.

| model | exact | route | project | session | noisy dictation | p50 | p95 | cost / 1000 requests | errors |
|---|---|---|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | 100% | 100% | 100% | 100% | - | 1345 ms | 12148 ms | $0.442 | 0 |

- **exact**: route, project and session all right.
- **project / session**: scored only on cases where the right answer is a task.
- **noisy dictation**: exact score on the `n*` cases, where speech-to-text mangled technical words.
- Latency is measured from this PC, including network; errors are excluded from latency and cost.
- p95 includes waiting out the API's `503 overloaded` replies (retried after 10 s, 20 s, 30 s);
  p50 is closer to a normal call. In real use the server tries the next model instead of waiting.
- A model with errors could not be scored on those cases (the API kept answering 503).
- Cost uses token counts reported by the API and prices in `eval/prices.json`.
