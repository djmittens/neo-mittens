"""RESCUE stage for step-centric recovery from batch/stage failures."""

import logging
from pathlib import Path
from typing import Optional

from ..config import GlobalConfig
from ..state import RalphState
from ..stages.base import Stage, StageResult, StageOutcome
from ..opencode import spawn_opencode, extract_metrics
from ..prompts import load_prompt, build_prompt_with_rules
from ..context import Metrics

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _build_rescue_prompt() -> Optional[str]:
    """Build the rescue prompt with rules. Returns None on failure."""
    prompt_text = load_prompt("rescue")
    if not prompt_text:
        logger.error("Failed to load rescue prompt")
        return None
    try:
        return build_prompt_with_rules(prompt_text, Path.cwd() / "app/ralph/AGENTS.md")
    except Exception as e:
        logger.error(f"Failed to build prompt: {e}")
        return None


def _extract_metrics_safe(output: str) -> Metrics:
    """Extract metrics with fallback to empty Metrics."""
    try:
        return extract_metrics(output) or Metrics()
    except Exception as e:
        logger.warning(f"Failed to extract metrics: {e}")
        return Metrics()


def _spawn_and_communicate(
    prompt: str, config: GlobalConfig
) -> tuple[Optional[str], Optional[StageResult]]:
    """Spawn OpenCode and get output. Returns (output, error_result)."""
    try:
        model = config.model if config.model else None
        process = spawn_opencode(
            prompt, cwd=Path.cwd(), timeout=config.timeout_ms, model=model
        )
    except Exception as e:
        logger.error(f"Failed to spawn OpenCode process: {e}")
        return None, StageResult(
            stage=Stage.RESCUE,
            outcome=StageOutcome.FAILURE,
            error=f"OpenCode spawn failed: {e}",
        )

    try:
        output_bytes, _ = process.communicate(timeout=config.timeout_ms // 1000)
        return output_bytes.decode("utf-8", errors="replace"), None
    except Exception as e:
        logger.error(f"Communication error: {e}")
        return None, StageResult(
            stage=Stage.RESCUE,
            outcome=StageOutcome.FAILURE,
            error=f"OpenCode communication failed: {e}",
        )


def run(state: RalphState, config: GlobalConfig) -> StageResult:
    """RESCUE stage: handles batch/stage failures with step-centric recovery."""
    if not state.rescue_stage:
        logger.warning("RESCUE called without rescue context")
        return StageResult(
            stage=Stage.RESCUE,
            outcome=StageOutcome.SKIP,
            error="No rescue context found",
        )

    logger.info(
        f"RESCUE: {state.rescue_stage} batch failed - {len(state.rescue_batch)} items, reason: {state.rescue_reason}"
    )

    prompt = _build_rescue_prompt()
    if prompt is None:
        return StageResult(
            stage=Stage.RESCUE,
            outcome=StageOutcome.FAILURE,
            error="Prompt build failed",
        )

    output, error_result = _spawn_and_communicate(prompt, config)
    if error_result:
        return error_result

    metrics = _extract_metrics_safe(output or "")
    return StageResult(
        stage=Stage.RESCUE,
        outcome=StageOutcome.SUCCESS,
        cost=metrics.total_cost,
        tokens_used=metrics.total_tokens_in + metrics.total_tokens_out,
    )
