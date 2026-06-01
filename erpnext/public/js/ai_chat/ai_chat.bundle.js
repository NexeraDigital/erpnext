// Copyright (c) 2026, NexeraDigital and contributors
// For license information, please see license.txt

/**
 * Global AI chat panel bundle. Loaded on every desk route via `app_include_js`
 * (erpnext/hooks.py). Mounts a single launcher + slide-over on `document.body`
 * once per desk session — but ONLY when `frappe.boot.ai_chat_enabled` is true
 * (set by erpnext.ai.chat.boot.boot_session; false for Guest and when the MCP
 * server is disabled). Styles ship in the sibling erpnext/public/scss/ai_chat.bundle.scss.
 */

import { AIChatController } from "./controller";

function init() {
	if (!window.frappe || !frappe.boot || !frappe.boot.ai_chat_enabled) return;
	if (frappe._ai_chat_controller) return; // singleton — survives SPA navigation
	frappe._ai_chat_controller = new AIChatController();
}

// app_ready fires in frappe.Application.startup() after the navbar/sidebar mount
// (frappe/public/js/frappe/desk.js). Registering here runs before that trigger.
$(document).on("app_ready", init);

// Fallback: if this bundle parsed after app_ready already fired, init once the
// DOM is ready. The singleton guard makes a double-call a no-op.
if (window.frappe && frappe.boot) {
	$(() => setTimeout(init, 0));
}
