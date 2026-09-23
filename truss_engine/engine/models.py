"""Load local models once; inference is called on dedicated worker threads."""
from pathlib import Path
import tempfile
from .names import hotword_text, action_label
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
        if self.options.get("decision_backend", "laya") == "laya":
            self.load_laya()
        self.load_transcription()

    def load_laya(self):
        import torch
        from huggingface_hub import snapshot_download
        from laya import Agent

        torch.set_num_threads(int(self.options.get("threads", 4)))
        model_dir = self.options.get("laya_model_path", "")
        if not model_dir:
            # Avoid downloading the bundled multilingual/typed checkpoints.
            model_dir = snapshot_download("convaiinnovations/laya", revision="1c5edc1", allow_patterns=["model.safetensors", "rl_agent_config.json", "tokenizer/*", "encoder/*.json"])
        self.agent = Agent(model_dir, device=self.options.get("device", "cpu"))
        # Laya defaults to a 192-token question head, which truncates larger
        # device lists. Allow every option's 48-token description plus markers,
        # instructions, and the full (at most 1000-character) partial transcript.
        self.agent.cfg.update(head_max_len=64 + 49 * 49, max_len=64 + 49 * 49 + 1024)

    def load_transcription(self):
        if self.options.get("stt_backend", "sherpa") == "nemotron":
            return  # The native runtime owns this model; never download Zipformer.
        if self.options.get("bundled_stt", True):
            from huggingface_hub import hf_hub_download
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
        # One shared distribution for every partial, with no name/verb prefilter
        # and no separately normalized groups. Stable order also avoids registry
        # ordering changes altering the question between otherwise equal runs.
        ordered = sorted(candidates, key=lambda candidate: (candidate["entity_id"], candidate["id"].endswith(":off")))
        labels = [action_label(text, candidate) for candidate in ordered]
        criteria = {"wait": "No requested action yet"}
        mapping = {}
        for candidate, label in zip(ordered, labels):
            key = label
            if labels.count(label) > 1:
                key += " (" + candidate.get("area", "") + "; " + candidate["id"] + ")"
            criteria[key] = None
            mapping[key] = candidate["id"]
        questions = {"action": {
            "type": "choice",
            "instructions": "Which action does the user explicitly request? Select wait if the command is incomplete, ambiguous, negated, or no listed action is requested.",
            "criteria": criteria,
        }}
        # Bundled ASR emits uppercase. Keep external providers' capitalization
        # from changing the decision for the same words.
        scores = self.agent.predict(text.upper(), questions)["answers"]["action"]["probabilities"]
        return {candidate_id: scores[key] for key, candidate_id in mapping.items()}

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
