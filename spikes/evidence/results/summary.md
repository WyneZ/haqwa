# Evidence: Gemini-direct vs Haqwa

Log: log.json (12 orders, 37 events). Real violations: A-2, A-8.
Gemini model: gemini-3.6-flash. Gemini got the rule, the owner's decisions, the event map and the full log.

| | Gemini direct | Haqwa checker |
|---|---|---|
| Runs | 10 | 10 |
| Exactly right (all violations, no false alarms) | 10/10 | 10/10 |
| Violations caught | 20/20 | 20/20 |
| False alarms (allowed orders flagged) | 0 | 0 |
| Time per run (median) | 10.7 s | 0.1 ms |
| Tokens per run (median, in / out) | 3189.0 / 85.0 | 0 / 0 |
| Same answer every run | yes | yes |

Orders Gemini flagged wrongly at least once: none.
Real violations Gemini missed at least once: none.
