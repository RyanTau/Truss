"""Load local models once; inference is called on dedicated worker threads."""
SHERPA_REPO = "csukuangfj/sherpa-onnx-streaming-zipformer-en-2023-06-26"
SHERPA_REVISION = "672fbf1"
SUFFIX = "epoch-99-avg-1-chunk-16-left-64.int8.onnx"


class LocalModels:
    def __init__(self, options):
        self.options = options
        self.agent = None
        self.recognizer = None

    def load(self):
        import torch
        from huggingface_hub import snapshot_download, hf_hub_download
        from laya import Agent

        torch.set_num_threads(int(self.options.get("threads", 4)))
        model_dir = self.options.get("laya_model_path", "")
        if not model_dir:
            # Avoid downloading the bundled multilingual/typed checkpoints.
            model_dir = snapshot_download("convaiinnovations/laya", revision="1c5edc1", allow_patterns=["model.safetensors", "rl_agent_config.json", "tokenizer/*", "encoder/*.json"])
        self.agent = Agent(model_dir, device=self.options.get("device", "cpu"))
        if self.options.get("bundled_stt", True):
            import sherpa_onnx
            files = {key: hf_hub_download(SHERPA_REPO, filename=f"{key}-{SUFFIX}", revision=SHERPA_REVISION) for key in ("encoder", "decoder", "joiner")}
            files["tokens"] = hf_hub_download(SHERPA_REPO, filename="tokens.txt", revision=SHERPA_REVISION)
            self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                **files, num_threads=int(self.options.get("threads", 4)), sample_rate=16000,
                feature_dim=80, decoding_method="greedy_search", provider="cpu",
                enable_endpoint_detection=False,
            )

    def score(self, text, candidates):
        # Small choice groups are faster and distinguish opposing operations
        # better than a separate binary question per action. Each group has an
        # explicit wait option. Scores across groups do NOT sum to one.
        probabilities = {}
        for offset in range(0, len(candidates), 4):
            batch = candidates[offset:offset + 4]
            criteria = {"wait": "No complete, unambiguous request for a listed action"}
            keys = []
            for index, candidate in enumerate(batch):
                key = candidate["id"].split(".", 1)[-1].replace(":", "_")
                if key in criteria:
                    key += f"_{index}"
                keys.append(key)
                description = candidate["label"]
                if candidate.get("area") and candidate["area"].casefold() not in description.casefold():
                    description += "; room: " + candidate["area"]
                if candidate.get("aliases"):
                    description += "; aliases: " + ", ".join(candidate["aliases"])
                criteria[key] = description
            questions = {"action": {
                "type": "choice",
                "instructions": "Which action does the user explicitly request? Select wait if the command is incomplete, ambiguous, negated, or no listed action is requested.",
                "criteria": criteria,
            }}
            result = self.agent.predict(text, questions)
            scores = result["answers"]["action"]["probabilities"]
            for index, candidate in enumerate(batch):
                probabilities[candidate["id"]] = scores[keys[index]]
        return probabilities

    def create_stream(self):
        if self.recognizer is None:
            raise ValueError("Bundled transcription is disabled")
        return self.recognizer.create_stream()

    def transcribe(self, stream, pcm, final=False):
        import numpy as np
        if pcm:
            samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
            stream.accept_waveform(16000, samples)
        if final:
            stream.accept_waveform(16000, np.zeros(8000, dtype=np.float32))
            stream.input_finished()
        while self.recognizer.is_ready(stream):
            self.recognizer.decode_stream(stream)
        return self.recognizer.get_result(stream)
