# 0.1.8

- Score every available action on each nonempty partial transcript, without deterministic name or operation filtering.
- Use one joint Laya distribution with a wait choice; preserve raw action probabilities.
- Include friendly names, aliases, and rooms in choices, with stable candidate ordering and a larger question token budget.
- Report `score_scope: joint_actions`. Existing execution thresholds and one-action-per-session behavior remain unchanged.

# 0.1.7

- Accept typed commands through Truss Response without initializing transcription.
- Allow close name misspellings, unique shortened names, and casual operation wording.
- Update Laya instructions to tolerate transcription errors and polite requests.
- Preserve configured thresholds, single-action execution, and expired receipt protection.
- Default new installations to 0.80; existing users can select 0.80 in Configure for more forgiving execution.

# 0.1.6

- Resolve explicit device names/Assist aliases and supported operations before one Laya execute/wait decision. Remove comparisons between unrelated groups' probabilities.
- Wait on missing/ambiguous names, incomplete commands, conflicting operations and recognized negation. Ineligible actions retain zero scores; model probabilities are not boosted or renormalized.
- Use streaming beam search and per-session names/aliases as recognition hints, with the pinned speech tokenizer and sentencepiece dependency.
- Include engine version and score scope in health; mark live scores as conditional on the resolved action.
- Update both engine and HA integration. Existing tokens and thresholds remain valid.

# 0.1.3

- Add the Truss thought-bubble/audio-wave icon to the companion app and integration brand assets.
- Include brand PNGs in manual installation packages and document HA/HACS icon compatibility.

# 0.1.2

- Set the Home Assistant minimum to 2026.1.0 for both the integration and companion app.

# 0.1.1

- Lower the Home Assistant minimum to 2025.11.0, whose MCP Streamable HTTP API is compatible with Truss.
- Use the backward-compatible add-on image type label for older Supervisor versions.

# 0.1.0

- Initial streaming Zipformer + Laya engine, with external STT WebSocket support.
- Authenticated streaming API and local model caching.
