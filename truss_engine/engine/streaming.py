"""Coalesce updates, retaining scored prefixes but rejecting ASR rewrites."""
import asyncio
import time


class LiveDecisions:
    def __init__(self, score, emit, candidates):
        self.score, self.emit, self.candidates = score, emit, candidates
        self.text = ""
        self.revision = 0
        self.scored_revision = 0
        self.changed = asyncio.Event()
        self.ended = False

    async def update(self, text):
        if not isinstance(text, str) or len(text) > 1000:
            raise ValueError("Transcript must contain at most 1000 characters")
        text = text.strip()
        if text == self.text:
            return
        self.text = text
        self.revision += 1
        await self.emit({"type": "partial", "revision": self.revision, "text": text})
        self.changed.set()

    def finish(self):
        self.ended = True
        self.changed.set()

    async def run(self):
        while True:
            await self.changed.wait()
            self.changed.clear()
            revision, text = self.revision, self.text
            if revision != self.scored_revision:
                start = time.perf_counter()
                probabilities = await self.score(text, self.candidates) if text else {c["id"]: 0.0 for c in self.candidates}
                # Appended words must not starve decisions on continuous speech.
                # A changed earlier word invalidates the score. A qualifying
                # prefix can commit before a later spoken correction.
                prefix_valid = bool(text) and self.text.casefold().startswith(text.casefold() + " ")
                if revision == self.revision or prefix_valid:
                    self.scored_revision = revision
                    metadata = {}
                    if hasattr(probabilities, "decision"):
                        metadata = {"decision": probabilities.decision, "trace": probabilities.trace, "score_scope": probabilities.score_scope}
                    await self.emit({"type": "probabilities", "revision": revision, "current_revision": self.revision, "text": text, "probabilities": probabilities, **metadata, "inference_ms": round((time.perf_counter() - start) * 1000, 1)})
            if self.ended and self.scored_revision == self.revision:
                return
