"""Expose the Truss streaming audio bridge as an Assist STT provider."""
import logging
from homeassistant.components import stt
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([TrussSTT(entry, hass.data[DOMAIN][entry.entry_id])])


class TrussSTT(stt.SpeechToTextEntity):
    _attr_name = "Truss Live"

    def __init__(self, entry, coordinator):
        self._attr_unique_id = entry.entry_id + "_stt"
        self.coordinator = coordinator

    @property
    def supported_languages(self):
        return ["en", "en-US", "en-GB", "en-AU"]

    @property
    def supported_formats(self):
        return [stt.AudioFormats.WAV]

    @property
    def supported_codecs(self):
        return [stt.AudioCodecs.PCM]

    @property
    def supported_bit_rates(self):
        return [stt.AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self):
        return [stt.AudioSampleRates.SAMPLERATE_16000]

    @property
    def supported_channels(self):
        return [stt.AudioChannels.CHANNEL_MONO]

    async def async_process_audio_stream(self, metadata, stream):
        try:
            receipt = await self.coordinator.async_stream(stream, metadata.language)
            return stt.SpeechResult(receipt, stt.SpeechResultState.SUCCESS)
        except Exception as err:
            # Do not log speech, URLs, tokens, or remote exception payloads.
            _LOGGER.error("Truss voice session failed (%s)", type(err).__name__)
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
