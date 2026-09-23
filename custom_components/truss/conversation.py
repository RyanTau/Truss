"""Return a session receipt to Assist without executing a command twice."""
import logging
from homeassistant.components import conversation
from homeassistant.helpers import intent
from .const import DOMAIN, RECEIPT_PREFIX

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([TrussConversation(entry, hass.data[DOMAIN][entry.entry_id])])


class TrussConversation(conversation.ConversationEntity):
    _attr_name = "Truss Response"
    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL

    def __init__(self, entry, coordinator):
        self._attr_unique_id = entry.entry_id + "_conversation"
        self.coordinator = coordinator

    @property
    def supported_languages(self):
        return ["en", "en-US", "en-GB", "en-AU"]

    async def async_process(self, user_input):
        response = intent.IntentResponse(language=user_input.language)
        message = self.coordinator.consume_receipt(user_input.text)
        if message is None:
            if user_input.text.strip().startswith(RECEIPT_PREFIX):
                message = "This Truss voice session has expired or was already handled."
            else:
                try:
                    message = await self.coordinator.async_text(user_input.text, user_input.language)
                except Exception as error:
                    _LOGGER.warning("Truss text command failed (%s)", type(error).__name__)
                    message = "Truss could not complete this command. Check the engine connection and Home Assistant logs."
        response.async_set_speech(message)
        return conversation.ConversationResult(response=response, conversation_id=user_input.conversation_id)
