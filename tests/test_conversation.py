"""Text dispatch and receipt replay protection at the Assist entry point."""
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch
from support import integration


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_and_receipts_use_separate_paths(self):
        conversation = types.ModuleType('homeassistant.components.conversation')
        conversation.ConversationEntity = object
        conversation.ConversationEntityFeature = types.SimpleNamespace(CONTROL=1)
        conversation.ConversationResult = lambda **kw: types.SimpleNamespace(**kw)
        intent = types.ModuleType('homeassistant.helpers.intent')
        intent.IntentResponse = lambda **kw: types.SimpleNamespace(async_set_speech=Mock())
        components = types.ModuleType('homeassistant.components')
        components.conversation = conversation
        helpers = types.ModuleType('homeassistant.helpers')
        helpers.intent = intent
        with patch.dict(sys.modules, {'homeassistant': types.ModuleType('homeassistant'),
                                      'homeassistant.components': components,
                                      'homeassistant.components.conversation': conversation,
                                      'homeassistant.helpers': helpers,
                                      'homeassistant.helpers.intent': intent}):
            module = integration('conversation')
        coordinator = types.SimpleNamespace(consume_receipt=Mock(return_value=None), async_text=AsyncMock(return_value='Requested: lamp on.'))
        agent = module.TrussConversation(types.SimpleNamespace(entry_id='test'), coordinator)
        user = types.SimpleNamespace(text='lamp on', language='en', conversation_id='chat')
        result = await agent.async_process(user)
        coordinator.async_text.assert_awaited_once_with('lamp on', 'en')
        self.assertEqual(result.conversation_id, 'chat')
        result.response.async_set_speech.assert_called_once_with('Requested: lamp on.')
        coordinator.async_text.reset_mock()
        user.text = 'truss-receipt:expired'
        result = await agent.async_process(user)
        coordinator.async_text.assert_not_awaited()
        self.assertIn('expired', result.response.async_set_speech.call_args.args[0])
        coordinator.consume_receipt.return_value = 'Already executed.'
        await agent.async_process(user)
        coordinator.async_text.assert_not_awaited()
