"""Centralized LLM cost calculation with Bedrock ARN support.

Environment variables
---------------------
- SWESMITH_COST_BASE_MODEL: Global override for the base model used in pricing.
  When set, ALL cost lookups use this model regardless of the ARN map.
  To use as a fallback instead, leave unset and rely on SWESMITH_ARN_MODEL_MAP.
  Default (if unset): "bedrock/anthropic.claude-opus-4-7"
- SWESMITH_ARN_MODEL_MAP: JSON mapping of ARN -> base model ID.
  Example: '{"bedrock/converse/arn:...": "bedrock/anthropic.claude-opus-4-7"}'
- SWESMITH_DISABLE_COST_REGISTRATION: Set to "1"/"true"/"yes" to skip
  litellm.register_model() registration.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

import litellm
from litellm.cost_calculator import completion_cost as _litellm_completion_cost

logger = logging.getLogger(__name__)

DEFAULT_BASE_MODEL = os.getenv("SWESMITH_COST_BASE_MODEL", "bedrock/anthropic.claude-opus-4-7")


def _load_arn_model_map() -> dict[str, str]:
    raw = os.getenv("SWESMITH_ARN_MODEL_MAP", "")
    if not raw.strip():
        return {}
    try:
        mapping = json.loads(raw)
        if not isinstance(mapping, dict):
            logger.warning("SWESMITH_ARN_MODEL_MAP is not a JSON object, ignoring.")
            return {}
        return {str(k): str(v) for k, v in mapping.items()}
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Failed to parse SWESMITH_ARN_MODEL_MAP: %s. Ignoring.", exc)
        return {}


_ARN_TO_BASE_MODEL: dict[str, str] = _load_arn_model_map()

_registration_lock = threading.Lock()
_registered = False


def _get_pricing_entry() -> dict[str, Any]:
    """Build a litellm pricing entry from litellm's own model cost data.

    Reads pricing for ``anthropic.claude-opus-4-7`` from litellm's bundled
    model cost map (which is kept up-to-date with upstream pricing).
    """
    native = litellm.model_cost.get("anthropic.claude-opus-4-7")
    if not (
        isinstance(native, dict)
        and isinstance(native.get("input_cost_per_token"), (int, float))
        and isinstance(native.get("output_cost_per_token"), (int, float))
    ):
        logger.warning(
            "litellm.model_cost missing 'anthropic.claude-opus-4-7' entry. "
            "Model registration will be skipped. Upgrade litellm if cost "
            "tracking breaks.",
        )
        return {}

    entry = dict(native)
    entry["litellm_provider"] = "bedrock"
    entry["mode"] = "chat"
    return entry


def register_swesmith_models() -> None:
    """Register Bedrock ARNs from SWESMITH_ARN_MODEL_MAP with litellm. Idempotent, thread-safe."""
    global _registered

    if _registered:
        return

    disable = os.getenv("SWESMITH_DISABLE_COST_REGISTRATION", "").lower()
    if disable in {"1", "true", "yes"}:
        logger.info(
            "SWESMITH_DISABLE_COST_REGISTRATION is set; skipping litellm.register_model()"
        )
        _registered = True
        return

    with _registration_lock:
        if _registered:
            return

        entry = _get_pricing_entry()
        if not entry:
            _registered = True
            return

        model_map: dict[str, dict[str, Any]] = {arn: entry for arn in _ARN_TO_BASE_MODEL}
        model_map[DEFAULT_BASE_MODEL] = entry

        try:
            litellm.register_model(model_map)
            logger.debug(
                "Registered %d SWE-smith Bedrock ARN(s) with litellm pricing map",
                len(model_map),
            )
        except Exception as exc:
            logger.warning(
                "Failed to register SWE-smith models with litellm: %s. "
                "Cost calculation will rely on base-model fallback only.",
                exc,
            )

        _registered = True


def _base_model_for(model: str | None) -> str:
    """Resolve the base model to use for pricing.

    Precedence:
    1. SWESMITH_COST_BASE_MODEL env var (global override, if set)
    2. Per-ARN mapping from SWESMITH_ARN_MODEL_MAP
    3. DEFAULT_BASE_MODEL constant (read once at import time)
    """
    if DEFAULT_BASE_MODEL != "bedrock/anthropic.claude-opus-4-7":
        # Env var was explicitly set at import time — honour as global override.
        return DEFAULT_BASE_MODEL

    if model and model in _ARN_TO_BASE_MODEL:
        return _ARN_TO_BASE_MODEL[model]

    return DEFAULT_BASE_MODEL


def _usage_tuple(response: Any) -> tuple[int, int]:
    try:
        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")
        if usage is None:
            return 0, 0
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        return prompt, completion
    except Exception:
        logger.debug("Failed to extract usage tuple from response", exc_info=True)
        return 0, 0


def _hidden_response_cost(response: Any) -> float | None:
    """Extract cost from litellm's internal bookkeeping.

    NOTE: ``_hidden_params`` is a private litellm attribute. It may change
    across litellm versions without notice. Treat this as best-effort.
    """
    hidden = getattr(response, "_hidden_params", None)
    if not isinstance(hidden, dict):
        return None
    value = hidden.get("response_cost")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_cost(response: Any, model: str | None = None) -> float:
    """Return USD cost of a litellm response. Never raises; returns 0.0 on failure."""
    register_swesmith_models()

    # Layer 1: litellm already computed the cost for us.
    hidden = _hidden_response_cost(response)
    if hidden is not None and hidden > 0:
        return hidden

    # Layer 2: explicit base-model override.
    base_model = _base_model_for(model)
    override_error: Exception | None = None
    try:
        cost = _litellm_completion_cost(completion_response=response, model=base_model)
        if cost is not None:
            return float(cost)
    except Exception as exc:
        override_error = exc

    # Layer 3: try without override (works if ARN was registered successfully).
    direct_error: Exception | None = None
    try:
        cost = _litellm_completion_cost(completion_response=response)
        if cost is not None:
            return float(cost)
    except Exception as exc:
        direct_error = exc

    # Layer 4: warn and return 0.0 per user policy.
    prompt_tokens, completion_tokens = _usage_tuple(response)
    logger.warning(
        "Cost calculation failed for model=%r (base_model=%r). "
        "prompt_tokens=%d completion_tokens=%d. "
        "Override error: %s. Direct error: %s. Returning 0.0.",
        model,
        base_model,
        prompt_tokens,
        completion_tokens,
        override_error,
        direct_error,
    )
    return 0.0


__all__ = [
    "register_swesmith_models",
    "safe_cost",
]
