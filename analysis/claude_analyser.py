"""
Anthropic Claude analyser — via Claude Code CLI (claude-agent-sdk).

Uses the Claude Code CLI for inference, supporting both API-key and
CLI-session authentication.  Pro / Max subscribers who are logged into
the CLI (``claude login``) do **not** need an API key.

Prerequisites
-------------
* Claude Code CLI installed:
    ``npm install -g @anthropic-ai/claude-code``
    or ``curl -fsSL https://claude.ai/install.sh | bash``
* Either:
    - Logged in via ``claude login`` (Pro / Max), **or**
    - An ``ANTHROPIC_API_KEY`` provided in the model settings.

Thinking modes
--------------
The ``thinking_mode`` parameter controls Claude's extended-thinking depth:
    ``"off"``   — thinking disabled
    ``"low"``   — lightweight reasoning (default)
    ``"medium"`` — moderate reasoning
    ``"high"``  — deep reasoning
    ``"max"``   — maximum reasoning budget
"""

from __future__ import annotations

import logging
import time
from typing import Literal, cast

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    TextBlock,
    ThinkingConfigDisabled,
    query,
)

from analysis._prompt_helper import (
    build_announcement_prompt,
    build_sentiment_prompt,
    parse_llm_response,
)
from analysis.base import LLMAnalyser
from config.constants import ANNOUNCEMENT_SYSTEM_PROMPT, SENTIMENT_SYSTEM_PROMPT
from config.settings import Settings
from core.models import AnalysisResult, AnalysisType, Form8KFiling, SentimentData

logger = logging.getLogger(__name__)

ThinkingMode = Literal["off", "low", "medium", "high", "max"]
VALID_THINKING_MODES: set[str] = {"off", "low", "medium", "high", "max"}


class ClaudeAnalyser(LLMAnalyser):
    """Cloud LLM analysis via Anthropic Claude (CLI-based).

    Uses the ``claude-agent-sdk`` to call the Claude Code CLI, which
    handles authentication automatically.  When an API key is provided
    it is passed to the CLI via the ``env`` parameter; otherwise the
    CLI uses its own session credentials.

    Args:
        settings: Application settings containing ``anthropic_api_key``
            (optional), ``claude_model``, and ``claude_cli_thinking_mode``.
    """

    _is_claude_agent_sdk: bool = True
    """Marker attribute used by consensus generator for provider detection."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model = settings.claude_model
        self._api_key = settings.anthropic_api_key
        self._thinking_mode: ThinkingMode = (
            cast(ThinkingMode, settings.claude_cli_thinking_mode)
            if settings.claude_cli_thinking_mode in VALID_THINKING_MODES
            else "low"
        )

    @property
    def provider_name(self) -> str:
        """Identifier for this provider."""
        return "claude-cli"

    @property
    def model_name(self) -> str:
        """Model identifier (e.g. ``claude-sonnet-4-20250514``)."""
        return self._model

    async def health_check(self) -> bool:
        """Verify the Claude Code CLI is reachable and authenticated.

        Sends a trivial prompt and checks for a non-empty response.

        Returns:
            True if the CLI responds successfully, False otherwise.
        """
        try:
            text = await self._query_claude(
                system_prompt="",
                user_prompt="Say ok",
            )
            return bool(text.strip())
        except Exception:
            logger.exception("Claude CLI health check failed")
            return False

    async def analyse_announcements(
        self,
        ticker: str,
        filings: list[Form8KFiling],
        user_context: str = "",
    ) -> AnalysisResult:
        """Analyse Form 8-K filings using Claude via CLI.

        Args:
            ticker: Stock symbol.
            filings: Form 8-K filings to analyse.
            user_context: Optional user-provided context.

        Returns:
            AnalysisResult with analysis_type=ANNOUNCEMENT.
        """
        return await self._call_llm(
            system_prompt=ANNOUNCEMENT_SYSTEM_PROMPT,
            user_prompt=build_announcement_prompt(ticker, filings, user_context),
            analysis_type=AnalysisType.ANNOUNCEMENT,
        )

    async def analyse_sentiment(
        self,
        ticker: str,
        sentiment: SentimentData,
        alert_context: dict | None = None,
        user_context: str = "",
    ) -> AnalysisResult:
        """Analyse market sentiment using Claude via CLI.

        Args:
            ticker: Stock symbol.
            sentiment: Aggregated sentiment data.
            alert_context: Optional price/volume context.
            user_context: Optional user-provided context.

        Returns:
            AnalysisResult with analysis_type=SENTIMENT.
        """
        return await self._call_llm(
            system_prompt=SENTIMENT_SYSTEM_PROMPT,
            user_prompt=build_sentiment_prompt(ticker, sentiment, alert_context, user_context),
            analysis_type=AnalysisType.SENTIMENT,
        )

    async def _query_claude(self, system_prompt: str, user_prompt: str) -> str:
        """Send a prompt to the Claude Code CLI and return the text response.

        Builds ``ClaudeAgentOptions`` with the configured model, thinking
        mode, and optional API key.  Iterates the streaming response and
        collects all ``TextBlock`` content from ``AssistantMessage`` objects.

        Args:
            system_prompt: System-level instruction for the model.
            user_prompt: User-level prompt with data to analyse.

        Returns:
            Concatenated text from all assistant text blocks.
        """
        env: dict[str, str] = {}
        if self._api_key:
            env["ANTHROPIC_API_KEY"] = self._api_key

        options = ClaudeAgentOptions(
            model=self._model,
            system_prompt=system_prompt or None,
            max_turns=1,
            allowed_tools=[],
            env=env,
            **self._thinking_options(),
        )

        parts: list[str] = []
        async for message in query(prompt=user_prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)

        return "".join(parts)

    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        analysis_type: AnalysisType,
    ) -> AnalysisResult:
        """Send a prompt to the Claude CLI and parse the structured response.

        Args:
            system_prompt: System-level instruction for the model.
            user_prompt: User-level prompt with data to analyse.
            analysis_type: The analysis type for the result.

        Returns:
            Parsed AnalysisResult.
        """
        start = time.monotonic()

        try:
            raw = await self._query_claude(system_prompt, user_prompt)
            latency = int((time.monotonic() - start) * 1000)

            return parse_llm_response(raw, self.provider_name, self._model, analysis_type, latency)

        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            logger.exception("Claude CLI analysis failed")
            return AnalysisResult(
                provider=self.provider_name,
                model=self._model,
                analysis_type=analysis_type,
                latency_ms=latency,
                error=str(e),
            )

    def _thinking_options(self) -> dict:
        """Build thinking-related kwargs for ``ClaudeAgentOptions``.

        Returns:
            Dict with either ``thinking`` (disabled) or ``effort`` key.
        """
        if self._thinking_mode == "off":
            return {"thinking": ThinkingConfigDisabled(type="disabled")}
        return {"effort": self._thinking_mode}
