# 0.1.7 validation

48 automated tests pass, including text-to-MCP execution without any ASR call, below-threshold text, receipt replay protection, typo matching, and ambiguous-name rejection. Package checks pass.

Offline CPU probe using the actual pinned Laya model (`scripts/smoke_selection.py`), September 23, 2026:

| Input | Resolved action | Raw execute score |
| --- | --- | --- |
| Turn the tall lamp on | Tall on | 0.9898 |
| Turn off the tall lamp | Tall off | 0.9844 |
| Turn on the Turkish lamp | Turkish on | 0.9814 |
| Turn off the Turkish lamp | Turkish off | 0.9857 |
| Turn off the colour light | Colour off | 0.9711 |
| THUNDER TALL LAMP ON | Tall on | 0.9315 |
| turksih lamp off please | Turkish off | 0.8830 |
| could you put the tal lamp on please | Tall on | 0.8698 |
| colored light off | Colour off | 0.8191 |
| tall lamp on please | Tall on | 0.8218 |

All ten clear or recoverable examples qualify at the new-install default 0.80. Existing installations retain their settings and need Configure to select 0.80. Other action scores were zero because they were ineligible, not because the model compared every device.

Unknown “colored lion”, missing target “Turn on”, negated “Do not turn on the tall lamp”, and state question “Is the tall lamp on?” all returned zero scores through resolver abstention.

These are a small development set, including examples used to tune the prompt, not an independent accuracy benchmark. No physical devices or user microphone were exercised. Permissive matching and lower thresholds can increase mistaken actions. Strongly garbled names, arbitrary paraphrases, and ambiguous names remain unsupported.
