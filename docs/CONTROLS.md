# Device attributes in Truss 0.1.12

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

## Thresholds and inspection

`truss_probabilities` uses `score_scope: staged_minimum` for this path. Its action
map is zero except for a complete selected control. That control's score is the
**minimum selected probability across all stages**. The configured threshold must
be reached by every stage; the configured margin must also be reached against
every stage's competitors, including wait. These scores are not a joint action
distribution or a calibrated probability of overall correctness. Existing
threshold values are preserved; inspect the trace before changing them.

Listen for **`truss_decision`** under Developer tools → Events for the transcript,
context, exact question, raw model results, and the selected device/attribute/value.
`truss_action` reports the bound attribute/value and execution outcome.
No action executes merely because the engine names a service; all service and
argument binding comes from the integration's own discovered catalogue.

The existing one-action-per-utterance rule, receipt protection, execution vetoes,
ASR rewrite handling, and no-retry behavior remain. A qualifying spoken prefix
can execute before subsequent words arrive; a later correction cannot undo it.

## Compatibility

The engine advertises `control_schema: device_attributes_v1` in `/health` for LAYA.
Older integrations keep their legacy joint on/off scoring path. Older engines and
Jev continue to receive legacy on/off/activation candidates; typed control
messages are rejected in Jev mode rather than treated as complete actions.

Capability and transport tests use HA doubles. Real-device operation still needs
verification on an installed Home Assistant instance. Model errors remain visible
in the staged trace and can prevent a correct command from reaching the threshold.
See the [offline model results](validation/controls-0.1.12.md) for this change.
