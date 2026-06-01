// Copyright (c) 2026, NexeraDigital and contributors
// For license information, please see license.txt

/**
 * Persistent floating launcher (bottom-right) + keyboard toggle (Ctrl/Cmd-J).
 * Mounted once on `document.body` so it survives SPA navigation. Visible only
 * when `frappe.boot.ai_chat_enabled` (the controller gates construction).
 */

export class Launcher {
	constructor(onToggle) {
		this.onToggle = onToggle;
		this.$el = $(`
			<button class="ai-chat-launcher" type="button"
				aria-label="${__("Open AI chat")}" title="${__("AI Chat (Ctrl/Cmd-J)")}">
				<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">
					<path fill="currentColor" d="M12 3c4.97 0 9 3.36 9 7.5S16.97 18 12 18c-.86 0-1.69-.1-2.48-.29L5 19.5l.86-3.13C4.08 15.05 3 12.91 3 10.5 3 6.36 7.03 3 12 3z"/>
				</svg>
			</button>
		`).appendTo(document.body);

		this.$el.on("click", () => this.onToggle());

		this._key = (e) => {
			if ((e.ctrlKey || e.metaKey) && (e.key === "j" || e.key === "J")) {
				e.preventDefault();
				this.onToggle();
			}
		};
		$(document).on("keydown.aichat", this._key);
	}

	setActive(active) {
		this.$el.toggleClass("active", !!active);
		this.$el.attr("aria-expanded", active ? "true" : "false");
	}

	destroy() {
		$(document).off("keydown.aichat", this._key);
		this.$el.remove();
	}
}
