# Staged RequestEval experiment

`engine.request_eval.RequestEval` is a synchronous, per-session experiment. It
does not replace the live engine's scorer or execute Home Assistant actions.
Pass a LAYA Router/Agent and dictionaries of devices and their allowed actions.
Call `update(full_transcript)` on every changed cumulative ASR transcript, or
iterate `eval_loop(transcripts)`. Use a worker thread if calling it from asyncio.

Each update asks the fixed questions in order:

1. Request: `in_progress` stops this update; `completed` advances.
2. Device: `not_specified` stops; otherwise select from the supplied devices.
3. Action: `not_specified` stops; otherwise select from that device's actions.

The question answers are added to `answers` and supplied to the next question.
An accepted request is appended to `answer_key`, including its device, action,
text, and all three answers. That history is supplied to subsequent model calls
so pronouns such as "it" can refer to a prior device. Unfinished requests are
re-evaluated on changed text, so corrected device names are not locked in.

The returned `context` is exactly `{"answered": "...", "unanswered": "..."}`.
`completed` contains only newly accepted decisions; duplicate input returns an
empty list. Once the third question resolves, that clause moves to `answered`.
The next clause stays in `unanswered` until it also resolves. Explicit boundaries
currently supported are "and then", "then", and "after that". General clause
segmentation without those linking phrases is not implemented.

An ASR rewrite of an already accepted prefix raises `TranscriptRewrite`; callers
must reconcile previously accepted decisions before `reset()`. There is no
automatic replay. Answers represent model decisions, not successful execution.

Run the interactive experiment from the repo root:

```powershell
.\.venv\Scripts\python.exe scripts\request_eval_demo.py
```

Enter each **full cumulative transcript** on a separate line, for example:

```text
Turn the Dyson on
Turn the Dyson on and then
Turn the Dyson on and then set
Turn the Dyson on and then set it to
Turn the Dyson on and then set it to 19 degrees
Turn the Dyson on and then set it to 19 degrees After that, turn of lights
```

The demo requires LAYA and loads a real Router on startup; importing RequestEval
does not download or load a model. Its device/action choices are illustrative:
temperature 19 is explicitly supplied, not freely extracted. Extend the choices
for other values. The experiment accepts model choices without an additional
probability threshold. Tests validate sequencing and state with a fake model;
they do not establish LAYA's semantic accuracy or the speed of three serial calls.
