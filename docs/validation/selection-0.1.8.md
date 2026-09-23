# 0.1.8 live probability validation

47 automated tests passed, including changing sub-threshold probability events before audio ends, every partial reaching Laya, all 48 candidate scores being mapped from a single question, duplicate-name preservation, text dispatch, and one-action-per-session execution. Syntax, translations, and packaging checks passed.

Actual pinned Laya model, offline Windows CPU, using `scripts/smoke_selection.py` with three lamps and their aliases:

| Partial transcript | Tall on | Ball/Turkish on | Colour on |
| --- | --- | --- | --- |
| Turn | 0.7724 | 0.1481 | 0.0509 |
| Turn on | 0.7725 | 0.1161 | 0.0845 |
| Turn on the tall | 0.9976 | 0.0011 | 0.0003 |

Off actions also had model scores throughout. No resolver supplied zeroes. These supplied partial strings test the real scorer with the final prompt; the streaming transport test uses doubles. No physical devices were operated.

Correct full off requests scored Tall off at 0.9652, Turkish off at 0.8694, and Colour off at 0.8163. This removes deterministic pre-inference safeguards and exposes the model's actual limitations: `colored light off` incorrectly ranked Colour **on** highest at 0.7845 (below default 0.80). A negated request scored Tall off at 0.9798, and a state question scored Tall on at 0.8769. Those wrong scores exceed the threshold, so the integration now vetoes recognized negations and state questions only at execution time. A separate execution check also vetoes a winner conflicting with explicit on/off wording. An end-to-end test verifies that .99 scores for these inputs are still published while MCP receives no action. This does not provide exhaustive natural-language safety coverage. Prompt changes tested during development did not reliably fix this. Joint scores are not calibrated correctness guarantees, and broader catalogs have not been accuracy-benchmarked. These examples are disclosed rather than hidden with resolver zeroes or forced score adjustment.

Old 0.1.6/0.1.7 results used resolved-action confirmation and do not establish accuracy for this joint scoring mode. The configured threshold, margin, and single-action limit remain unchanged.
