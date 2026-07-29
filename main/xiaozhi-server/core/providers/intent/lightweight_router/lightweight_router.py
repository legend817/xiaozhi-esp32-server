from ..base import IntentProviderBase
from typing import List, Dict
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


class IntentProvider(IntentProviderBase):
    async def detect_intent(self, conn, dialogue_history: List[Dict], text: str) -> str:
        """
        Lightweight router does not run a separate LLM intent pass.

        The actual tool selection is handled in ConnectionHandler by deterministic
        local routing before the main LLM request. This provider keeps the common
        intent-provider contract compatible with nointent/function_call providers.
        """
        logger.bind(tag=TAG).debug(
            "Using LightweightRouterProvider, returning continue chat"
        )
        return '{"function_call": {"name": "continue_chat"}}'
