# Device attributes in Truss 0.1.14

Update and restart both the HA integration and the engine. Local LAYA now follows
**action needed → device → attribute → value**. Every changed transcript is
evaluated against the selected, exposed entities. No entity names or numeric
targets are built into the evaluator.

The integration rebuilds the control catalogue for each utterance using entity
attributes, supported feature flags, registered HA services, and discovered MCP
tools. It rechecks exposure, selection, availability and the current supported
values immediately before execution. The engine receives declarative controls;
it cannot supply arbitrary service names or arguments for execution.

| Capability | Model control | Discovery / execution |
| --- | --- | --- |
| Power | Binary on/off | Existing MCP tools, or registered domain services; feature flags for fans/climate/media players |
| Scene/script activation | Choice | Existing MCP activation tool |
| Climate target | Score | Single-target feature, `min_temp`, `max_temp`, `target_temp_step`, HA unit; `climate.set_temperature` |
| Climate mode/preset/fan/swing | Choice | Supported modes, feature flags, corresponding service |
| Light brightness | Score | Brightness-capable color modes; `light.turn_on` with `brightness_pct` |
| Cover position | Score, or open/close choices | Position feature and `set_cover_position`; otherwise advertised open/close features/services |
| Fan speed/preset | Score/choice | Reported speed step or presets and supported features |
| Media volume/mute | Score/binary | Feature flags; percent converted to `volume_level` 0–1, or `is_volume_muted` |
| Media source/sound mode | Choice | Reported source/sound-mode lists and feature flags |
| Select/input select | Choice | Exact `options`; `select_option` |
| Number/input number | Score | Actual `min`, `max`, `step`, unit; `set_value` |

TV channels work when the device exposes them as selectable sources, or through
an exposed select entity. HA does **not** provide a universal list of every TV's
channels. Truss does not infer an arbitrary channel range or guess a `play_media`
payload. See HA's [media player capabilities](https://developers.home-assistant.io/docs/core/entity/media-player/).
Climate support follows HA's [target feature validation](https://developers.home-assistant.io/blog/2024/09/24/climate-set-temp-validation/).
Two-target heating/cooling ranges are not implemented.

Numeric scales preserve the reported step. Missing/invalid ranges or steps and
scales with more than 128 values are omitted rather than silently rounded to a
different step. Other usable attributes remain available. A session supports at
most 24 entities, 192 control candidates and 4096 total offered values.

Score questions expose the full ordered level distribution. The selected setting
is the highest-probability supported level, **not** a weighted average that could
blend several distinct targets. Binary and discrete choices map back to their
exact local values. Missing/unsupported values wait for more speech.

## Selection and inspection

Each stage selects its highest-probability option, including wait. There is no
minimum probability or lead requirement and no user setting to change selection.
Exact ties use question order. A wait winner leaves the decision incomplete and
does not execute. Existing saved thresholds and margins are ignored.

`truss_probabilities` uses `score_scope: staged_minimum` for this path. Its action
map is zero except for a complete selected control. That control's score is the
**minimum selected probability across all stages**. Probabilities and lead margins
remain diagnostic evidence, not execution requirements. These scores are not a
joint action distribution or calibrated probabilities of overall correctness.

Listen for **`truss_decision`** under Developer tools → Events for the transcript,
context, exact question, raw model results, and the selected device/attribute/value.
`truss_action` reports the bound attribute/value and execution outcome.
No action executes merely because the engine names a service; all service and
argument binding comes from the integration's own discovered catalogue.

Local LAYA and hosted Jev use the evaluator and prompt format from `testing.py`: uppercase
`Completed actions` and `In progress request`, with instructions to classify
only the pending request and use completed text only to resolve references.
Completed text is consumed once. Explicit separators `then`, `and then`, and
`after that` split chained requests; arbitrary `and` clauses are not split.

Each accepted decision executes once in order, up to 32 per engine session.
An execution failure stops remaining decisions without retry and clears stored
context. Receipt protection, execution vetoes and ASR rewrite checks remain.
A qualifying spoken prefix can execute before later words arrive; a subsequent
correction cannot undo it.

Typed Assist messages retain completed/pending text by user and conversation ID.
Send `/reset` to clear it. Context expires after ten minutes and is limited to
1000 characters, with up to 100 conversations cached. Separate voice utterances
remain independent because the STT interface does not provide a conversation ID
before inference; chained actions within a voice utterance share context.

## Compatibility

The engine advertises `control_schema: device_attributes_v1` in `/health` for both LAYA and Jev.
Version 0.1.13 also negotiates `conversation_schema: completed_pending_v1`.
Update and restart both engine and integration to enable the conversation path.
Unnegotiated clients retain the previous single-decision behavior.
Older integrations keep their legacy joint on/off scoring path. Older engines
continue to receive legacy on/off/activation candidates. Jev supports typed
controls and conversation context starting in 0.1.14. Configure the backend
and API key on the engine; see [Jev setup](JEV.md).

Capability and transport tests use HA doubles. Real-device operation still needs
verification on an installed Home Assistant instance. Model errors remain visible
in the staged trace and can select an incorrect action or wait option.
See the [offline model results](validation/controls-0.1.12.md) for this change.
