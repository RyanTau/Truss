# Release verification

This source is a development release. Automated mock-model checks are necessary but insufficient for claiming Home Assistant/device compatibility.

1. Run `scripts/set_repository.py` with the published repository URL. Verify badges, code owner, HACS metadata, and Supervisor repository discovery. Choose the project's distribution license before publishing; upstream model/library licenses remain separate.
2. Run unit/transport tests and package checks in CI.
3. Build the engine image for amd64 and aarch64. Check pinned model downloads, CPU PyTorch and sherpa wheels, cold-start RAM/disk usage, and warm inference.
4. Install in isolated HA 2026.1 and current-release instances. Test config/options flow, MCP detection, invalid tokens, unload/reload, expired token recovery, startup retries, and entity exposure changes.
5. Select both Truss entities in an Assist pipeline. With a real microphone and test light, verify an action arrives BEFORE the audio end message and exactly once.
6. Verify MCP JSON and SSE responses against the official MCP Server. Check a tool-level intent failure is not announced as success. Confirm namespaced tools target only the selected entity.
7. Test two simultaneous voice devices, network loss during transcription, model errors, MCP timeout after execution, service shutdown, and speech cancellation. Confirm no command is retried automatically.
8. Run a labelled corpus of actual partial transcripts; measure early/wrong/missed actions and choose thresholds empirically. Include Australian accents, room noise, negation, truncated and revised hypotheses, and overlapping entity names.
9. Compare actual device state changes with reported MCP acceptance. Independent physical-state verification is not implemented yet.
10. Test the external STT protocol with the specific provider adapter you plan to advertise. Do not advertise generic Whisper, Ollama, or Wyoming compatibility.
