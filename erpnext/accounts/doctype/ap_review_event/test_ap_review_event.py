# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Spec 10 — AP Review Event DocType + emit_review_event primitive."""

import json
from io import BytesIO

import frappe
from frappe.tests import IntegrationTestCase
from pypdf import PdfWriter

from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
	REVIEW_ACTION_TAKEN_VALUES,
	ROOT_CAUSE_TAG_VALUES,
	create_capture_from_file,
	emit_review_event,
)


def _make_capture():
	buf = BytesIO()
	writer = PdfWriter()
	writer.add_blank_page(width=200, height=200)
	writer.add_metadata({"/Subject": frappe.generate_hash(length=10)})
	writer.write(buf)
	f = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": "review-event-" + frappe.generate_hash(length=6) + ".pdf",
			"is_private": 1,
			"content": buf.getvalue(),
		}
	).insert(ignore_permissions=True)
	return create_capture_from_file(file_doc=f, source_context="AP Review Event test")


class TestAPReviewEvent(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	# AC-10-9: every action_taken + root_cause_tag value persists; defaults applied;
	# returns a valid name linked to the capture.
	def test_ac_10_9_emit_each_action_and_root_cause(self):
		cap = _make_capture()
		for action in REVIEW_ACTION_TAKEN_VALUES:
			name = emit_review_event(cap, action_taken=action, root_cause_tag="other")
			self.assertTrue(frappe.db.exists("AP Review Event", name))
			row = frappe.get_doc("AP Review Event", name)
			self.assertEqual(row.action_taken, action)
			self.assertEqual(row.capture, cap.name)
			self.assertEqual(row.clerk, "Administrator")  # defaulted from session
			self.assertTrue(row.created)
		for tag in ROOT_CAUSE_TAG_VALUES:
			name = emit_review_event(cap, action_taken="field_corrected", root_cause_tag=tag)
			self.assertEqual(frappe.db.get_value("AP Review Event", name, "root_cause_tag"), tag)

	# AC-10-10: a value outside the fixed vocabulary fails Select validation on insert.
	def test_ac_10_10_invalid_vocabulary_raises(self):
		cap = _make_capture()
		with self.assertRaises(frappe.ValidationError):
			emit_review_event(cap, action_taken="not_a_real_action")
		with self.assertRaises(frappe.ValidationError):
			emit_review_event(cap, action_taken="field_corrected", root_cause_tag="not_a_tag")

	# AC-10-11: fields_changed JSON round-trips; time_to_resolve_seconds is an Int;
	# two calls yield two distinct events.
	def test_ac_10_11_fields_changed_roundtrip_and_distinct(self):
		cap = _make_capture()
		changed = {"invoice_date": {"from": "2026-01-01", "to": "2026-01-02"}}
		n1 = emit_review_event(
			cap,
			action_taken="field_corrected",
			fields_changed=changed,
			time_to_resolve_seconds=42,
		)
		row = frappe.get_doc("AP Review Event", n1)
		self.assertEqual(json.loads(row.fields_changed), changed)
		self.assertEqual(row.time_to_resolve_seconds, 42)
		n2 = emit_review_event(cap, action_taken="field_corrected")
		self.assertNotEqual(n1, n2)
		self.assertEqual(
			frappe.db.count("AP Review Event", {"capture": cap.name}), 2
		)

	# AC-10-11 (default resolve time): omitted time_to_resolve_seconds derives from creation.
	def test_default_time_to_resolve_is_int(self):
		cap = _make_capture()
		name = emit_review_event(cap, action_taken="field_corrected")
		ttr = frappe.db.get_value("AP Review Event", name, "time_to_resolve_seconds")
		self.assertIsInstance(ttr, int)
		self.assertGreaterEqual(ttr, 0)
