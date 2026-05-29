# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""BaseTool — the contract every MCP tool implements.

Each tool declares Pydantic ``input_model`` / ``output_model`` models. The JSON
Schema the LLM sees is generated from those (``model_json_schema``), NOT inferred
from a function signature — this is the deliberate fix for the FAC/frappe-mcp
anti-pattern the plan rejects in §3.4 (which silently drops enum/min/max/format).

``run`` is the funnel a subclass's ``execute`` is wrapped in: validate args ->
execute (which does its own ``has_permission`` + permitted-names queries) ->
strip control chars from output (L10) -> shape into MCP ``structuredContent``.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

# L10: control characters (except tab/newline/carriage-return) are stripped from
# returned strings — ERPNext text fields (vendor names, descriptions) are treated
# as a prompt-injection vector and must not carry terminal/control sequences.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _strip_controls(value: Any) -> Any:
	if isinstance(value, str):
		return _CONTROL_CHARS.sub("", value)
	if isinstance(value, list):
		return [_strip_controls(v) for v in value]
	if isinstance(value, dict):
		return {k: _strip_controls(v) for k, v in value.items()}
	return value


class BaseTool:
	"""Subclass and set the class attributes + implement ``execute``."""

	name: str = ""
	title: str = ""
	description: str = ""
	required_scope: str = ""
	annotations: dict = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}
	input_model: type[BaseModel] = None
	output_model: type[BaseModel] = None
	# When True, ``execute`` returns a list and structuredContent is {"results": [...]}.
	output_is_list: bool = True

	# ----- schema (the LLM's contract) -----

	@classmethod
	def input_schema(cls) -> dict:
		schema = cls.input_model.model_json_schema()
		# MCP requires a valid JSON Schema object, never null.
		schema.setdefault("type", "object")
		return schema

	@classmethod
	def output_schema(cls) -> dict | None:
		if cls.output_model is None:
			return None
		item = cls.output_model.model_json_schema()
		if cls.output_is_list:
			return {
				"type": "object",
				"properties": {"results": {"type": "array", "items": item}},
				"required": ["results"],
			}
		return item

	# ----- execution -----

	def execute(self, args: BaseModel) -> Any:
		"""Implemented by subclasses. Must call ``has_permission`` before any read.

		Returns a list[dict] (when ``output_is_list``) or a dict.
		"""
		raise NotImplementedError

	def run(self, raw_args: dict | None) -> dict:
		"""Validate args, execute, sanitize output, shape into structuredContent."""
		args = self.input_model.model_validate(raw_args or {})
		result = self.execute(args)
		result = _strip_controls(result)
		if self.output_is_list:
			return {"results": list(result or [])}
		return result if isinstance(result, dict) else {"value": result}
