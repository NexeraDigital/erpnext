// Copyright (c) 2026, Nexera and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Document Capture", {
	refresh(frm) {
		render_status_display(frm);
		clear_inline_actions(frm);
		render_inline_upload_button(frm);
		render_inline_confirm_button(frm);
		render_inline_change_currency_button(frm);
		render_inline_validation_actions(frm);
		render_inline_promote_button(frm);
		render_inline_manager_buttons(frm);
		render_inline_issue_payment_button(frm);
	},
});

// State-based retry for the final cascade hop. Visible when a capture is
// approved-and-ready but no Payment Entry exists — the exact "stuck after
// async cascade failure" state. Calling issue_mock_payment_for synchronously
// surfaces any error via frappe.call's toast instead of burying it in
// Error Log like the worker-side enqueue path does.
function render_inline_issue_payment_button(frm) {
	if (frm.is_new()) return;
	const approved = ["Auto Approved", "Manager Approved"].includes(frm.doc.approval_status);
	if (!approved) return;
	if (frm.doc.payment_readiness !== "Ready for Payment") return;
	if (frm.doc.payment_entry) return;

	append_inline_actions(
		frm,
		"mock_payment_section",
		build_inline_action_row([
			{
				label: __("Issue Mock Payment"),
				style: "primary",
				on_click: async () => {
					try {
						await frappe.call({
							method: "erpnext.accounts.doctype.document_capture.document_capture.issue_mock_payment_for",
							args: { capture: frm.doc.name },
							freeze: true,
							freeze_message: __("Issuing mock payment…"),
						});
					} catch (_) {
						return;
					}
					frm.reload_doc();
				},
			},
		]),
	);
}

// Change Currency is a post-confirmation override for the canonical case
// where the fake OCR (hash-driven, ignores image content) proposed a
// currency that doesn't match the supplier's Payable account, causing
// Promote to fail with a Frappe currency-mismatch error. Visible while
// the capture exists and isn't promoted yet; placed in the AP Review
// section so it's visually adjacent to the read-only Final Currency field.
function render_inline_change_currency_button(frm) {
	if (frm.is_new()) return;
	if (frm.doc.promotion_status === "Promoted") return;
	if (!frm.doc.final_currency) return;

	append_inline_actions(
		frm,
		"review_section",
		build_inline_action_row([
			{
				label: __("Change Currency"),
				style: "default",
				on_click: () => open_change_currency_dialog(frm),
			},
		]),
	);
}

function open_change_currency_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Change capture currency"),
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "intro",
				options: `<div class="text-muted small mb-3">${__(
					"Update the capture's final currency. Use this when OCR's proposed currency was wrong (the fake OCR ignores image content) or doesn't match the supplier's payable account. After changing, click Re-run Validation or Promote to retry the blocked step.",
				)}</div>`,
			},
			{
				fieldtype: "Link",
				fieldname: "currency",
				label: __("Final Currency"),
				options: "Currency",
				reqd: 1,
				default: frm.doc.final_currency,
			},
		],
		primary_action_label: __("Change"),
		async primary_action(values) {
			if (values.currency === frm.doc.final_currency) {
				// Nothing to change — close without hitting the server.
				d.hide();
				return;
			}
			try {
				await frappe.call({
					method: "frappe.client.set_value",
					args: {
						doctype: "Document Capture",
						name: frm.doc.name,
						fieldname: "final_currency",
						value: values.currency,
					},
					freeze: true,
					freeze_message: __("Updating currency…"),
				});
			} catch (_) {
				return; // Frappe surfaces the error as a toast
			}
			d.hide();
			frappe.show_alert({
				message: __("Final currency updated to {0}.", [values.currency]),
				indicator: "green",
			});
			frm.reload_doc();
		},
	});
	d.show();
}

// All inline action buttons live in a `.ap-inline-actions` row that we
// render into the relevant section's wrapper. Clear stale instances on
// every refresh so toggling state doesn't accumulate duplicates.
function clear_inline_actions(frm) {
	frm.$wrapper.find(".ap-inline-actions").remove();
}

function append_inline_actions(frm, section_fieldname, $row) {
	// Section Break fields are NOT registered in frm.fields_dict — they're
	// managed by frm.layout.sections. Frappe's Section.make() writes the
	// fieldname onto the wrapper as a data attribute (form/section.js:32),
	// so the wrapper is reachable via a DOM selector against the form.
	const $section = frm.$wrapper.find(`.form-section[data-fieldname="${section_fieldname}"]`);
	if (!$section.length) return;
	// Drop the row right after the section's heading; fall back to
	// prepending into .section-body if the section has no `.section-head`
	// (label hidden) — keeps the button visible at the top of the section.
	const $head = $section.find(".section-head").first();
	if ($head.length) {
		$head.after($row);
	} else {
		const $body = $section.find(".section-body").first();
		if ($body.length) {
			$body.prepend($row);
		} else {
			$section.prepend($row);
		}
	}
}

function build_inline_action_row(buttons) {
	const $row = $('<div class="ap-inline-actions row" style="margin: 0 0 12px 0;"></div>');
	const $col = $('<div class="col-sm-12" style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center;"></div>');
	buttons.forEach((b) => {
		const $btn = $(`<button type="button" class="btn btn-sm btn-${b.style || "default"}">${frappe.utils.escape_html(b.label)}</button>`);
		$btn.on("click", b.on_click);
		$col.append($btn);
	});
	$row.append($col);
	return $row;
}

function render_inline_upload_button(frm) {
	if (frm.doc.source_file || frm.doc.source_file_url) {
		// File already attached — offer a quick "View source" link instead
		// of the Upload button so the clerk can pop the original in a new
		// tab from the Source section header.
		render_inline_view_source_link(frm);
		return;
	}
	const $row = build_inline_action_row([
		{
			label: __("Upload Invoice"),
			style: "primary",
			on_click: () => upload_invoice_file(frm),
		},
	]);
	append_inline_actions(frm, "source_section", $row);
}

function render_inline_view_source_link(frm) {
	if (!frm.doc.source_file_url) return;
	const $row = $('<div class="ap-inline-actions row" style="margin: 0 0 12px 0;"></div>');
	const $col = $('<div class="col-sm-12" style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center;"></div>');
	const $link = $(
		`<a href="${frm.doc.source_file_url}" target="_blank" rel="noopener" class="btn btn-sm btn-default">${__("View Source Document")}</a>`,
	);
	const $filename = $(
		`<span class="text-muted small">${frappe.utils.escape_html(frm.doc.source_filename || "")}</span>`,
	);
	$col.append($link).append($filename);
	$row.append($col);
	append_inline_actions(frm, "source_section", $row);
}

// Confirm Fields surfaces only at status=Proposed (OCR ran, awaiting human
// review). Clicking it opens a dialog pre-filled with the proposed values;
// the clerk overrides any incorrect field and clicks Confirm. The cascade
// then auto-runs validation.
function render_inline_confirm_button(frm) {
	if (frm.is_new()) return;
	if (frm.doc.status !== "Proposed" || frm.doc.ocr_status !== "Proposed") return;
	const $row = build_inline_action_row([
		{
			label: __("Confirm Fields"),
			style: "primary",
			on_click: () => open_confirm_dialog(frm),
		},
	]);
	append_inline_actions(frm, "ocr_section", $row);
}

function open_confirm_dialog(frm) {
	const proposed_label = (val) =>
		__("OCR proposed: {0}", [val !== undefined && val !== null && val !== "" ? val : __("(none)")]);

	// Build a "View Source Document" link so the clerk can open the original
	// artifact (PDF / PNG / JPG) in a new tab while reviewing the proposal.
	const source_link_html = frm.doc.source_file_url
		? `<div class="mb-3">
				<a href="${frm.doc.source_file_url}" target="_blank" rel="noopener" class="btn btn-sm btn-default">
					${frappe.utils.icon ? frappe.utils.icon("link-url", "sm") : ""}
					${__("View Source Document")}
				</a>
				<span class="text-muted small" style="margin-left: 8px;">${frappe.utils.escape_html(frm.doc.source_filename || "")}</span>
			</div>`
		: `<div class="text-muted small mb-3">${__("No source file linked — review with caution.")}</div>`;

	const d = new frappe.ui.Dialog({
		title: __("Confirm OCR-proposed fields"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "intro_html",
				options: `<div class="text-muted small mb-3">${__(
					"Review what OCR proposed below. Edit any field that needs correction, then click Confirm. The cascade will auto-validate from there.",
				)}</div>
				${source_link_html}`,
			},
			{
				fieldtype: "Section Break",
			},
			{
				fieldtype: "Link",
				fieldname: "supplier",
				label: __("Supplier"),
				options: "Supplier",
				default: frm.doc.proposed_supplier,
				description: proposed_label(frm.doc.proposed_supplier),
			},
			{
				fieldtype: "Data",
				fieldname: "supplier_invoice_no",
				label: __("Supplier Invoice No"),
				default: frm.doc.proposed_supplier_invoice_no,
				description: proposed_label(frm.doc.proposed_supplier_invoice_no),
			},
			{
				fieldtype: "Column Break",
			},
			{
				fieldtype: "Date",
				fieldname: "invoice_date",
				label: __("Invoice Date"),
				default: frm.doc.proposed_invoice_date,
				description: proposed_label(frm.doc.proposed_invoice_date),
			},
			{
				fieldtype: "Float",
				fieldname: "total_amount",
				label: __("Total Amount"),
				default: frm.doc.proposed_total_amount,
				description: proposed_label(frm.doc.proposed_total_amount),
			},
			{
				fieldtype: "Link",
				fieldname: "currency",
				label: __("Currency"),
				options: "Currency",
				default: frm.doc.proposed_currency,
				description: proposed_label(frm.doc.proposed_currency),
			},
			{
				fieldtype: "Section Break",
			},
			{
				fieldtype: "Small Text",
				fieldname: "review_notes",
				label: __("Review notes (optional)"),
			},
		],
		primary_action_label: __("Confirm"),
		primary_action(values) {
			// confirm_extracted_fields applies corrections OVER the proposal,
			// so sending all five fields is harmless when the clerk accepts
			// the proposed value unchanged — final == proposed in that case.
			const corrections = {
				supplier: values.supplier,
				supplier_invoice_no: values.supplier_invoice_no,
				invoice_date: values.invoice_date,
				total_amount: values.total_amount,
				currency: values.currency,
			};
			frappe.call({
				method: "erpnext.accounts.doctype.document_capture.document_capture.confirm_extracted_fields_for",
				args: {
					capture: frm.doc.name,
					corrections: JSON.stringify(corrections),
					notes: values.review_notes || null,
				},
				freeze: true,
				freeze_message: __("Recording confirmation — cascade will auto-validate…"),
				callback() {
					d.hide();
					frm.reload_doc();
				},
			});
		},
	});
	d.show();
}

// When validation lands at Blocked, surface the recovery actions inline
// under the Validation section. Re-run Validation is always available;
// Create Supplier is gated to Accounts Manager AND only shown when the
// block is specifically the "unknown supplier" case, to keep the SoD
// boundary (AP clerks can't self-create the vendor they're about to pay).
function render_inline_validation_actions(frm) {
	if (frm.is_new()) return;
	if (frm.doc.validation_status !== "Blocked") return;

	const buttons = [
		{
			label: __("Re-run Validation"),
			style: "primary",
			on_click: () => rerun_validation(frm),
		},
	];

	if (
		frm.doc.supplier_match_status === "Unknown"
		&& frappe.user.has_role("Accounts Manager")
	) {
		buttons.push({
			label: __("Create Supplier"),
			style: "default",
			on_click: () => open_create_supplier_dialog(frm),
		});
	}

	append_inline_actions(frm, "validation_section", build_inline_action_row(buttons));
}

function rerun_validation(frm) {
	frappe.call({
		method: "erpnext.accounts.doctype.document_capture.document_capture.validate_for_purchase_invoice_for",
		args: { capture: frm.doc.name },
		freeze: true,
		freeze_message: __("Re-running validation…"),
		callback() {
			frm.reload_doc();
		},
		error() {
			// Frappe shows the server error as a toast automatically.
			// Reload anyway so partial state (validation_message,
			// supplier_match_status) is reflected.
			frm.reload_doc();
		},
	});
}

function open_create_supplier_dialog(frm) {
	const proposed_name = frm.doc.final_supplier || frm.doc.proposed_supplier || "";
	const default_country =
		(frappe.boot && frappe.boot.sysdefaults && frappe.boot.sysdefaults.country) || "";

	const d = new frappe.ui.Dialog({
		title: __("Create new Supplier"),
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "intro",
				options: `<div class="text-muted small mb-3">${__(
					"Create the missing Supplier so this capture can revalidate. The new record is created with normal permissions — no AP-side bypass. After saving, click Re-run Validation.",
				)}</div>`,
			},
			{
				fieldtype: "Data",
				fieldname: "supplier_name",
				label: __("Supplier Name"),
				reqd: 1,
				default: proposed_name,
			},
			{
				fieldtype: "Link",
				fieldname: "supplier_group",
				label: __("Supplier Group"),
				options: "Supplier Group",
				reqd: 1,
			},
			{
				fieldtype: "Link",
				fieldname: "country",
				label: __("Country"),
				options: "Country",
				reqd: 1,
				default: default_country,
			},
		],
		primary_action_label: __("Create"),
		// Async/await so each step serializes: insert → set_value → save →
		// hide → toast. Mixing callback-style frappe.call with .then chains
		// on frm.save() races against Frappe's post-save lifecycle and
		// leaves the dialog open (observed bug, 2026-05-27).
		async primary_action(values) {
			let r;
			try {
				r = await frappe.call({
					method: "frappe.client.insert",
					args: {
						doc: {
							doctype: "Supplier",
							supplier_name: values.supplier_name,
							supplier_group: values.supplier_group,
							country: values.country,
						},
					},
					freeze: true,
					freeze_message: __("Creating Supplier…"),
				});
			} catch (e) {
				// Frappe surfaces the server error as a toast automatically;
				// leave the dialog open so the user can correct the inputs.
				return;
			}

			if (!r || !r.message) return;
			const supplier_name = r.message.name;

			await frm.set_value("final_supplier", supplier_name);
			// Only save when set_value actually dirtied the form. If the
			// capture's final_supplier was already this name (common case:
			// the user accepted the OCR proposal in Confirm Fields, then
			// hit Create Supplier with the same name), frm.save() rejects
			// with "No changes in document" and aborts the rest of this
			// chain — leaving the dialog open and the user confused.
			if (frm.is_dirty()) {
				await frm.save();
			}

			d.hide();
			frappe.show_alert({
				message: __("Supplier {0} created. Click Re-run Validation to retry.", [
					supplier_name,
				]),
				indicator: "green",
			});
		},
	});
	d.show();
}

// Promote surfaces at validation_status=Validated AND not yet promoted.
// The dialog pre-fills from AP Closed Loop Settings (Single DocType) so a
// well-configured site is one click away from creating the PI; per-invoice
// overrides are still allowed for unusual spend.
function render_inline_promote_button(frm) {
	if (frm.is_new()) return;
	if (frm.doc.validation_status !== "Validated") return;
	if (frm.doc.promotion_status === "Promoted") return;

	append_inline_actions(
		frm,
		"promotion_section",
		build_inline_action_row([
			{
				label: __("Promote to Purchase Invoice"),
				style: "primary",
				on_click: () => open_promote_dialog(frm),
			},
		]),
	);
}

async function open_promote_dialog(frm) {
	// Pull settings defaults via a whitelisted helper that reads the raw
	// stored values (not frappe.db.get_doc, which auto-populates empty
	// Link fields from session defaults — that pulls in cross-company
	// warehouses and other footguns).
	let settings = {};
	try {
		const r = await frappe.call({
			method: "erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings.get_promote_defaults_for_ui",
		});
		settings = (r && r.message) || {};
	} catch (_) {
		settings = {};
	}

	const default_company =
		settings.default_company || frappe.defaults.get_user_default("company") || "";

	const d = new frappe.ui.Dialog({
		title: __("Promote to Purchase Invoice"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "intro",
				options: `<div class="text-muted small mb-3">${__(
					"Promote this validated capture to a Purchase Invoice. The four required fields are organization-level GL coding choices — pre-filled from AP Closed Loop Settings, override per-invoice if needed. The cascade will auto-route approval from here.",
				)}</div>`,
			},
			{
				fieldtype: "Section Break",
				label: __("Required"),
			},
			{
				fieldtype: "Link",
				fieldname: "company",
				label: __("Company"),
				options: "Company",
				reqd: 1,
				default: default_company,
			},
			{
				fieldtype: "Link",
				fieldname: "item_code",
				label: __("Item Code"),
				options: "Item",
				reqd: 1,
				default: settings.default_item_code,
				get_query() {
					// Fixed-asset items require per-Company GL account setup
					// (Fixed Asset Account per Item Group). For the pilot's
					// expense-style spend, exclude them so the user doesn't
					// pick a footgun item and hit "Missing Account" on insert.
					return {
						filters: {
							is_fixed_asset: 0,
							disabled: 0,
							is_purchase_item: 1,
						},
					};
				},
			},
			{
				fieldtype: "Column Break",
			},
			{
				fieldtype: "Link",
				fieldname: "expense_account",
				label: __("Expense Account"),
				options: "Account",
				reqd: 1,
				default: settings.default_expense_account,
				get_query() {
					// Account list is huge; filter to expense/income types.
					return {
						filters: {
							root_type: ["in", ["Expense", "Income"]],
							is_group: 0,
						},
					};
				},
			},
			{
				fieldtype: "Link",
				fieldname: "cost_center",
				label: __("Cost Center"),
				options: "Cost Center",
				reqd: 1,
				default: settings.default_cost_center,
				get_query() {
					return { filters: { is_group: 0 } };
				},
			},
			{
				fieldtype: "Section Break",
				label: __("Optional"),
				collapsible: 1,
				collapsed: 1,
			},
			{
				fieldtype: "Link",
				fieldname: "warehouse",
				label: __("Warehouse"),
				options: "Warehouse",
				default: settings.default_warehouse,
			},
			{
				fieldtype: "Link",
				fieldname: "uom",
				label: __("UoM"),
				options: "UOM",
				default: settings.default_uom,
			},
		],
		primary_action_label: __("Promote"),
		async primary_action(values) {
			const defaults = {
				company: values.company,
				item_code: values.item_code,
				expense_account: values.expense_account,
				cost_center: values.cost_center,
				warehouse: values.warehouse || null,
				uom: values.uom || null,
			};
			try {
				await frappe.call({
					method: "erpnext.accounts.doctype.document_capture.document_capture.promote_to_purchase_invoice_for",
					args: {
						capture: frm.doc.name,
						defaults: JSON.stringify(defaults),
					},
					freeze: true,
					freeze_message: __("Creating Purchase Invoice — cascade will route approval…"),
				});
			} catch (_) {
				// Frappe shows the server error as a toast; leave dialog
				// open so the user can correct (bad account, missing item, etc.).
				return;
			}
			d.hide();
			frm.reload_doc();
		},
	});
	d.show();
}

// Approve / Reject buttons surface only when the capture is parked at
// Pending Manager AND the current user holds the recorded approver role.
// The server-side `record_manager_decision` enforces the same role gate;
// hiding the buttons is purely a UX nicety so clerks aren't shown actions
// they can't take.
function render_inline_manager_buttons(frm) {
	if (frm.is_new()) return;
	if (frm.doc.approval_status !== "Pending Manager") return;

	const required_role = frm.doc.assigned_approver_role || "Accounts Manager";
	if (!frappe.user.has_role(required_role)) return;

	const $row = build_inline_action_row([
		{
			label: __("Approve"),
			style: "primary",
			on_click: () => prompt_manager_decision(frm, true),
		},
		{
			label: __("Reject"),
			style: "danger",
			on_click: () => prompt_manager_decision(frm, false),
		},
	]);
	append_inline_actions(frm, "approval_section", $row);
}

function prompt_manager_decision(frm, approve) {
	const title = approve ? __("Approve invoice capture") : __("Reject invoice capture");
	const primary_label = approve ? __("Approve") : __("Reject");
	const notes_label = approve ? __("Approval notes (optional)") : __("Reason for rejection");

	frappe.prompt(
		{
			fieldname: "notes",
			fieldtype: "Small Text",
			label: notes_label,
			reqd: approve ? 0 : 1,
		},
		(values) => {
			frappe.call({
				method: "erpnext.accounts.doctype.document_capture.document_capture.record_manager_decision_for",
				args: {
					capture: frm.doc.name,
					approve: approve ? 1 : 0,
					notes: values.notes || null,
				},
				freeze: true,
				freeze_message: approve
					? __("Recording approval — cascade will issue mock payment…")
					: __("Recording rejection — payment will be blocked…"),
				callback() {
					frm.reload_doc();
				},
			});
		},
		title,
		primary_label,
	);
}

// action_required and action_required_reason are system-managed flags. We
// hide the raw fields and surface their meaning as a colored banner +
// dashboard indicator so a clerk can see at-a-glance whether the capture
// is waiting on them, blocked, or flowing on its own. The boolean stays in
// the database for list-view filtering.
function render_status_display(frm) {
	frm.set_df_property("action_required", "hidden", 1);
	frm.set_df_property("action_required_reason", "hidden", 1);

	frm.dashboard.clear_headline();

	if (frm.is_new()) return;

	if (frm.doc.action_required && frm.doc.action_required_reason) {
		const color = action_severity_color(frm);
		frm.set_intro(__("⚠ {0}", [frm.doc.action_required_reason]), color);
		frm.dashboard.add_indicator(__("Action Required"), color);
		return;
	}

	frm.set_intro(null);

	if (frm.doc.payment_lifecycle_status === "Closed") {
		frm.dashboard.add_indicator(__("Closed"), "green");
	} else if (frm.doc.payment_lifecycle_status === "Blocked") {
		frm.dashboard.add_indicator(__("Blocked"), "red");
	} else {
		frm.dashboard.add_indicator(__("In Progress"), "blue");
	}
}

function action_severity_color(frm) {
	const reason = frm.doc.action_required_reason || "";
	if (
		frm.doc.status === "Unsupported" ||
		frm.doc.approval_status === "Rejected" ||
		frm.doc.payment_lifecycle_status === "Blocked" ||
		// Auto-step failures (surfaced by _run_cascade_step) are real
		// errors, not "waiting for human review" — render them red.
		reason.startsWith("Auto-step")
	) {
		return "red";
	}
	return "orange";
}

function upload_invoice_file(frm) {
	new frappe.ui.FileUploader({
		// Standalone upload: not attached to this doc (the doc may be new
		// and unsaved). We link the resulting File record into source_file
		// so validate() can hydrate source_filename and source_file_url.
		allow_multiple: false,
		// AP invoices contain supplier names and amounts — always private.
		// Locking both flags so a clerk can't accidentally make the artifact
		// world-readable.
		make_attachments_public: false,
		allow_toggle_private: false,
		// Optimize is left visible: for PDFs it auto-defaults to off, but
		// for large images Frappe defaults it on, and the clerk should be
		// able to uncheck it so the original bytes are preserved for OCR
		// and audit.
		upload_notes: __("Keep Optimize off so the original artifact is preserved for OCR and audit."),
		on_success(file_doc) {
			frm.set_value("source_file", file_doc.name);
			frm.set_value("source_filename", file_doc.file_name);
			frm.set_value("source_file_url", file_doc.file_url);
			if (frm.is_dirty()) {
				frm.save();
			}
		},
	});
}
