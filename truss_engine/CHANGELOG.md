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
