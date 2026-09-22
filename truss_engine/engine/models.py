"""Load local models once; inference is called on dedicated worker threads."""
from pathlib import Path
import tempfile
from .names import hotword_text, resolve_action
SHERPA_REPO = "csukuangfj/sherpa-onnx-streaming-zipformer-en-2023-06-26"
SHERPA_REVISION = "672fbf1"
SUFFIX = "epoch-99-avg-1-chunk-16-left-64.int8.onnx"


class LocalModels:
    def __init__(self, options):
        self.options = options
        self.agent = None
        self.recognizer = None
        self.speech_tokenizer = None

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
            import sentencepiece
            files = {key: hf_hub_download(SHERPA_REPO, filename=f"{key}-{SUFFIX}", revision=SHERPA_REVISION) for key in ("encoder", "decoder", "joiner")}
            files["tokens"] = hf_hub_download(SHERPA_REPO, filename="tokens.txt", revision=SHERPA_REVISION)
            bpe_model = hf_hub_download(SHERPA_REPO, filename="bpe.model", revision=SHERPA_REVISION)
            self.speech_tokenizer = sentencepiece.SentencePieceProcessor(model_file=bpe_model)
            # sherpa's native tokenizer reads the matching SentencePiece vocab
            # into memory during construction. No additional remote vocab needed.
            with tempfile.TemporaryDirectory(prefix="truss-vocab-") as directory:
                vocab = Path(directory) / "bpe.vocab"
                vocab.write_text("\n".join(f"{self.speech_tokenizer.id_to_piece(i)}\t{self.speech_tokenizer.get_score(i)}" for i in range(self.speech_tokenizer.get_piece_size())) + "\n", encoding="utf-8")
                self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                    **files, num_threads=int(self.options.get("threads", 4)), sample_rate=16000,
                    feature_dim=80, decoding_method="modified_beam_search", max_active_paths=4,
                    modeling_unit="bpe", bpe_vocab=str(vocab), hotwords_score=1.5, provider="cpu",
                    enable_endpoint_detection=False,
                )

    def score(self, text, candidates):
        # Resolve the explicit target before asking Laya about its actions. This
        # avoids both cross-group score comparisons and high-confidence guesses
        # about an unrelated device. Zeroes mean ineligible, not model estimates.
        probabilities = {c["id"]: 0.0 for c in candidates}
        resolved = resolve_action(text, candidates)
        if resolved is None:
            return probabilities
        candidate, spoken_name = resolved
        operation = candidate["id"].rsplit(":", 1)[-1]
        verb = "Activate" if candidate["entity_id"].split(".")[0] in ("scene", "script") else "Turn " + operation
        criteria = {"wait": "No complete, unambiguous request for a listed action", "execute": verb + " " + spoken_name}
        questions = {"action": {
            "type": "choice",
            "instructions": "Which action does the user explicitly request? Select wait if the command is incomplete, ambiguous, negated, or no listed action is requested.",
            "criteria": criteria,
        }}
        # Bundled ASR emits uppercase. Keep external providers' capitalization
        # from changing the decision for the same words.
        scores = self.agent.predict(text.upper(), questions)["answers"]["action"]["probabilities"]
        probabilities[candidate["id"]] = scores["execute"]
        return probabilities

    def create_stream(self, candidates=None):
        if self.recognizer is None:
            raise ValueError("Bundled transcription is disabled")
        hints = hotword_text(candidates or [], self.speech_tokenizer) if self.speech_tokenizer else ""
        return self.recognizer.create_stream(hotwords=hints) if hints else self.recognizer.create_stream()

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
