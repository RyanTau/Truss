"""TypeSafe's hosted Jev decision API; no Home Assistant credentials are sent."""
import math
import json
import logging

import aiohttp

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
LOGGER = logging.getLogger(__name__)


class JevClient:
    def __init__(self, options):
        self.api_key = options.get("typesafe_api_key", "").strip()
        self.model = options.get("jev_model", "jev-latest").strip()
        if not self.api_key or not self.model:
            raise ValueError("Jev requires typesafe_api_key and jev_model")
        self.session = None

    async def start(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

    async def close(self):
        if self.session:
            await self.session.close()

    async def score(self, text, candidates):
        criteria = {"wait": "No clear requested action yet; wait for more speech"}
        mapping = {}
        for index, candidate in enumerate(sorted(candidates, key=lambda c: c["id"])):
            key = f"action_{index}"
            criteria[key] = {"action": candidate["label"], "name": candidate.get("name", ""),
                             "aliases": candidate.get("aliases", []), "room": candidate.get("area", "")}
            mapping[key] = candidate["id"]
        body = {"model": self.model, "state": {"transcript": text}, "questions": {"action": {
            "type": "choice", "criteria": criteria,
            "instructions": "Which listed smart-home action is explicitly requested in the live transcript so far? Allow spelling and transcription errors. Choose wait for unclear targets, incomplete requests, negation, conflicting actions, state questions, or ordinary conversation. Do not invent missing words.",
        }}}
        # No redirects or automatic retries: avoid leaking the key or executing
        # decisions delayed by repeated provider requests during live speech.
        async with self.session.post(ENDPOINT, json=body, headers={"Authorization": "Bearer " + self.api_key}, allow_redirects=False) as response:
            if response.status != 200:
                LOGGER.warning("Jev decision request failed: HTTP %s", response.status)
                raise RuntimeError(f"Jev returned HTTP {response.status}")
            if response.content_length and response.content_length > 1_000_000:
                raise ValueError("Jev response is too large")
            raw = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                raw.extend(chunk)
                if len(raw) > 1_000_000:
                    raise ValueError("Jev response is too large")
            payload = json.loads(raw)
        try:
            answer = payload["answers"]["action"]
            scores = answer["probabilities"]
            valid = (
                answer["type"] == "choice"
                and isinstance(scores, dict) and set(scores) == set(criteria)
                and all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1
                        for p in [*scores.values(), answer["confidence"]])
                and abs(sum(scores.values()) - 1) < .02
                and answer["choice"] in scores
                and scores[answer["choice"]] >= max(scores.values()) - 1e-6
            )
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("Invalid Jev probability response")
        return {candidate_id: scores[key] for key, candidate_id in mapping.items()}
