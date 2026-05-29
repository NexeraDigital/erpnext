# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Per-model token pricing for OCR cost estimation.

The Anthropic API returns token usage but not cost, so we estimate it from a
local rate table. These figures are for **monitoring / audit only** — the
authoritative spend is in Anthropic's billing console. Update the table when
Anthropic changes pricing or when a new model is added.

Rates are USD per 1,000,000 tokens (input, output).
"""

from __future__ import annotations

# model id -> (input $/Mtok, output $/Mtok). Estimates as of 2026-05.
PER_MODEL_PRICING = {
	"claude-haiku-4-5-20251001": (1.0, 5.0),
	"claude-sonnet-4-6": (3.0, 15.0),
	"claude-opus-4-8": (15.0, 75.0),
}

# Match on a model-family prefix when an exact id isn't in the table (e.g. a
# dated variant we haven't enumerated), so cost estimates degrade gracefully.
_PREFIX_PRICING = {
	"claude-haiku-4-5": (1.0, 5.0),
	"claude-sonnet-4-6": (3.0, 15.0),
	"claude-opus-4-8": (15.0, 75.0),
}


def _rate_for(model: str):
	if not model:
		return None
	if model in PER_MODEL_PRICING:
		return PER_MODEL_PRICING[model]
	for prefix, rate in _PREFIX_PRICING.items():
		if model.startswith(prefix):
			return rate
	return None


def estimate_cost_usd(calls) -> tuple[float, bool]:
	"""Sum estimated cost across a list of call records.

	``calls`` is a list of dicts: {"model", "input_tokens", "output_tokens"}.
	Returns (cost_usd, complete) where complete is False if any call's model
	had no known rate (so the cost is a lower bound).
	"""
	total = 0.0
	complete = True
	for c in calls or []:
		rate = _rate_for(c.get("model"))
		if rate is None:
			complete = False
			continue
		in_rate, out_rate = rate
		total += (c.get("input_tokens") or 0) / 1_000_000 * in_rate
		total += (c.get("output_tokens") or 0) / 1_000_000 * out_rate
	return round(total, 6), complete
