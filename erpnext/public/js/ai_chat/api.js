// Copyright (c) 2026, NexeraDigital and contributors
// For license information, please see license.txt

/**
 * Thin client wrappers over the whitelisted chat endpoints
 * (`erpnext.ai.chat.api.*`). `frappe.call` posts to `/api/method/…` with the
 * session cookie + CSRF token; the whitelisted methods reject Guest server-side
 * (frappe default `allow_guest=False`). The Anthropic key never reaches here —
 * the turn runs server-side and streams back over realtime.
 */

function call(method, args) {
	return new Promise((resolve, reject) => {
		frappe.call({
			method: `erpnext.ai.chat.api.${method}`,
			args,
			callback: (r) => resolve(r.message),
			error: (r) => reject(r),
		});
	});
}

export const api = {
	// context is sent as a JSON string hint only; the server re-validates + re-fetches it.
	startTurn: (message, conversation, context) =>
		call("start_turn", {
			message,
			conversation: conversation || null,
			context: context ? JSON.stringify(context) : null,
		}),
	getConversation: (conversation) => call("get_conversation", { conversation }),
	listConversations: (limit = 30) => call("list_conversations", { limit }),
	clearConversation: (conversation) => call("clear_conversation", { conversation }),
};
