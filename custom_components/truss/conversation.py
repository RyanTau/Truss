"""Return a session receipt to Assist without executing a command twice."""
from homeassistant.components import conversation
from homeassistant.helpers import intent
from .const import DOMAIN


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
            message = "Select Truss Live as speech-to-text and Truss Response as the conversation agent. This agent only responds to Truss voice sessions."
        response.async_set_speech(message)
        return conversation.ConversationResult(response=response, conversation_id=user_input.conversation_id)
