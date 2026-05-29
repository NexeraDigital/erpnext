// Copyright (c) 2026, Nexera and Contributors
// License: GNU General Public License v3. See license.txt

// Frappe's Password field type renders with the same UI as a User account
// password: a strength meter ("Weak / Excellent") backed by zxcvbn. That UX
// is appropriate when a user is picking their own login password — it is
// misleading for external service API keys, where strength is determined by
// the provider, not by the operator pasting it in.
//
// We keep the Password field type because we want its encryption-at-rest
// behavior (the value lands in __Auth, not in tabSingles, via Frappe's
// standard get/set_encrypted_password). We just suppress the misleading
// strength-meter UI on this specific form.
//
// The eye-toggle (show/hide the entered value) is left alone — it's useful
// for verifying a pasted key by sight.
//
// Frappe source for the password control: apps/frappe/frappe/public/js/frappe/form/controls/password.js
// The selector `.password-strength-indicator` is added at line 12 of that file.

frappe.ui.form.on("AI Provider Settings", {
	refresh(frm) {
		["anthropic_api_key", "openai_api_key"].forEach((fname) => {
			const field = frm.get_field(fname);
			if (!field) return;
			field.$wrapper.find(".password-strength-indicator").hide();
		});
	},
});
