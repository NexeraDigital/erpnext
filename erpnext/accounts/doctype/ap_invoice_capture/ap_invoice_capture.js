// Copyright (c) 2026, Nexera and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("AP Invoice Capture", {
	refresh(frm) {
		if (!frm.doc.source_file && !frm.doc.source_file_url) {
			frm.add_custom_button(__("Upload Invoice"), () => upload_invoice_file(frm));
		}
		render_status_display(frm);
	},
});

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
	if (
		frm.doc.status === "Unsupported" ||
		frm.doc.approval_status === "Rejected" ||
		frm.doc.payment_lifecycle_status === "Blocked"
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
