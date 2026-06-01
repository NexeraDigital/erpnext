// Copyright (c) 2026, NexeraDigital and contributors
// For license information, please see license.txt

import { api } from "./api";
import { ContextTracker } from "./context";
import { TurnStream } from "./stream";

/**
 * The non-blocking right-side slide-over: header (title + live context chip with
 * pin/clear + history + new), a message log, and a composer. State lives in
 * memory on this singleton, so it survives SPA navigation. Streaming is driven by
 * TurnStream; the current context is a hint captured by ContextTracker and sent
 * to the server, which always re-validates + re-fetches it.
 */

const MOBILE_BREAKPOINT = 768;

export class Panel {
	constructor() {
		this.conversation = null;
		this.sending = false;
		this.stream = null;
		this.assistantBubble = null;
		this.isOpen = false;
		this._build();
		this.context = new ContextTracker((hint) => this._renderContext(hint));
	}

	// --- DOM -----------------------------------------------------------------
	_build() {
		this.$el = $(`
			<div class="ai-chat-panel" role="dialog" aria-modal="false" aria-label="${__("AI Chat")}" hidden>
				<div class="ai-chat-header">
					<div class="ai-chat-title">${__("AI Chat")}</div>
					<div class="ai-chat-header-actions">
						<button class="ai-chat-icon-btn ai-chat-history" type="button" aria-label="${__("Conversations")}" title="${__("Conversations")}">${frappe.utils.icon("list", "sm")}</button>
						<button class="ai-chat-icon-btn ai-chat-new" type="button" aria-label="${__("New chat")}" title="${__("New chat")}">${frappe.utils.icon("add", "sm")}</button>
						<button class="ai-chat-icon-btn ai-chat-close" type="button" aria-label="${__("Close")}" title="${__("Close")}">${frappe.utils.icon("close", "sm")}</button>
					</div>
				</div>
				<div class="ai-chat-context" hidden>
					<span class="ai-chat-context-dot" aria-hidden="true"></span>
					<span class="ai-chat-context-label"></span>
					<div class="ai-chat-context-actions">
						<button class="ai-chat-context-pin" type="button">${__("Pin")}</button>
						<button class="ai-chat-context-clear" type="button" aria-label="${__("Clear context")}">${__("Clear")}</button>
					</div>
				</div>
				<div class="ai-chat-history-list" hidden role="menu" aria-label="${__("Conversations")}"></div>
				<div class="ai-chat-messages" role="log" aria-live="polite" aria-label="${__("Conversation")}"></div>
				<div class="ai-chat-status" hidden aria-live="polite"></div>
				<form class="ai-chat-composer">
					<textarea class="ai-chat-input" rows="1" aria-label="${__("Message")}"
						placeholder="${__("Ask about what you're viewing…")}"></textarea>
					<button class="ai-chat-send" type="submit" aria-label="${__("Send")}" disabled>${frappe.utils.icon("send", "sm")}</button>
				</form>
			</div>
		`).appendTo(document.body);

		this.$messages = this.$el.find(".ai-chat-messages");
		this.$status = this.$el.find(".ai-chat-status");
		this.$input = this.$el.find(".ai-chat-input");
		this.$send = this.$el.find(".ai-chat-send");
		this.$context = this.$el.find(".ai-chat-context");
		this.$historyList = this.$el.find(".ai-chat-history-list");

		this.$el.find(".ai-chat-close").on("click", () => this.close());
		this.$el.find(".ai-chat-new").on("click", () => this.newChat());
		this.$el.find(".ai-chat-history").on("click", () => this.toggleHistory());
		this.$el.find(".ai-chat-context-pin").on("click", () => this._togglePin());
		this.$el.find(".ai-chat-context-clear").on("click", () => this.context.clear());

		this.$el.find(".ai-chat-composer").on("submit", (e) => {
			e.preventDefault();
			this.send();
		});
		this.$input.on("input", () => this._autosize());
		this.$input.on("keydown", (e) => {
			if (e.key === "Enter" && !e.shiftKey) {
				e.preventDefault();
				this.send();
			}
		});
		this._key = (e) => {
			if (e.key === "Escape" && this.isOpen) this.close();
		};
		$(document).on("keydown.aichatpanel", this._key);

		this._renderEmpty();
	}

	// --- open/close ----------------------------------------------------------
	toggle() {
		this.isOpen ? this.close() : this.open();
	}

	open() {
		this.isOpen = true;
		this.$el.attr("hidden", null).addClass("open");
		document.body.classList.add("ai-chat-open");
		this.onOpenChange?.(true);
		setTimeout(() => this.$input.trigger("focus"), 50);
	}

	close() {
		this.isOpen = false;
		this.$el.removeClass("open");
		document.body.classList.remove("ai-chat-open");
		this.$historyList.attr("hidden", "");
		this.onOpenChange?.(false);
		// keep DOM (state preserved); just visually hidden via CSS transition
		setTimeout(() => {
			if (!this.isOpen) this.$el.attr("hidden", "");
		}, 200);
	}

	// --- context chip --------------------------------------------------------
	_renderContext(hint) {
		const label = ContextTracker.label(hint);
		if (!label) {
			this.$context.attr("hidden", "");
			return;
		}
		this.$context.attr("hidden", null);
		this.$context.find(".ai-chat-context-label").text(`${__("Context")}: ${label}`);
		this.$el
			.find(".ai-chat-context-pin")
			.text(this.context.isPinned() ? __("Unpin") : __("Pin"))
			.toggleClass("active", this.context.isPinned());
	}

	_togglePin() {
		this.context.isPinned() ? this.context.unpin() : this.context.pin();
	}

	// --- history / threads ---------------------------------------------------
	async toggleHistory() {
		const hidden = this.$historyList.attr("hidden") != null;
		if (!hidden) {
			this.$historyList.attr("hidden", "");
			return;
		}
		this.$historyList.html(`<div class="ai-chat-history-empty text-muted">${__("Loading…")}</div>`).attr("hidden", null);
		try {
			const rows = await api.listConversations(30);
			if (!rows.length) {
				this.$historyList.html(`<div class="ai-chat-history-empty text-muted">${__("No conversations yet.")}</div>`);
				return;
			}
			this.$historyList.empty();
			rows.forEach((r) => {
				const $row = $(`<button class="ai-chat-history-row" type="button" role="menuitem"></button>`)
					.text(r.title || __("Untitled"))
					.on("click", () => {
						this.$historyList.attr("hidden", "");
						this.loadConversation(r.name);
					});
				this.$historyList.append($row);
			});
		} catch (e) {
			this.$historyList.html(`<div class="ai-chat-history-empty text-muted">${__("Could not load conversations.")}</div>`);
		}
	}

	async loadConversation(name) {
		try {
			const res = await api.getConversation(name);
			this.conversation = name;
			this._renderMessages(res.messages || []);
		} catch (e) {
			frappe.show_alert({ message: __("Could not open that conversation."), indicator: "red" });
		}
	}

	newChat() {
		this.stream?.stop();
		this.conversation = null;
		this.assistantBubble = null;
		this.sending = false;
		this._setComposerEnabled(true);
		this._clearStatus();
		this._renderEmpty();
		this.$input.trigger("focus");
	}

	// --- send + stream -------------------------------------------------------
	async send() {
		const text = (this.$input.val() || "").trim();
		if (!text || this.sending) return;
		this.sending = true;
		this.$input.val("");
		this._autosize();
		this._setComposerEnabled(false);
		this._dismissEmpty();
		this._appendMessage("User", text);
		this._showStatus(__("Thinking…"));

		const hint = this.context.get();
		try {
			const res = await api.startTurn(text, this.conversation, hint);
			this.conversation = res.conversation;
			this._startStream(res.conversation);
		} catch (e) {
			this._clearStatus();
			this._failTurn(this._errMessage(e));
		}
	}

	_startStream(conversation) {
		this.assistantBubble = null;
		this.stream?.stop();
		this.stream = new TurnStream(conversation, {
			onStatus: (t) => this._showStatus(t),
			onDelta: (t) => this._appendDelta(t),
			onDone: (d) => this._finishTurn(d),
			onError: (t) => this._failTurn(t),
		});
	}

	async _finishTurn() {
		this._clearStatus();
		this.sending = false;
		this._setComposerEnabled(true);
		// Reconcile against the persisted thread (covers a missed socket event).
		if (this.conversation) {
			try {
				const res = await api.getConversation(this.conversation);
				this._renderMessages(res.messages || []);
			} catch (e) {
				/* keep the streamed bubble as-is */
			}
		}
		this.$input.trigger("focus");
	}

	_failTurn(message) {
		this._clearStatus();
		this.sending = false;
		this._setComposerEnabled(true);
		const $err = $(`<div class="ai-chat-msg ai-chat-msg-error" role="alert"></div>`);
		$err.append($(`<div class="ai-chat-bubble"></div>`).text(message || __("Something went wrong.")));
		const $retry = $(`<button class="ai-chat-retry btn btn-xs" type="button"></button>`).text(__("Retry"));
		$retry.on("click", () => {
			const last = this._lastUserMessage();
			$err.remove();
			if (last) {
				this.$input.val(last);
				this.send();
			}
		});
		$err.append($retry);
		this.$messages.append($err);
		this._scroll();
	}

	// --- rendering -----------------------------------------------------------
	_renderMessages(messages) {
		this.$messages.empty();
		this.assistantBubble = null;
		if (!messages.length) {
			this._renderEmpty();
			return;
		}
		messages.forEach((m) => {
			if (m.error) {
				const $err = $(`<div class="ai-chat-msg ai-chat-msg-error"></div>`);
				$err.append($(`<div class="ai-chat-bubble"></div>`).text(m.content || m.error));
				this.$messages.append($err);
			} else {
				this._appendMessage(m.role, m.content);
			}
		});
		this._scroll();
	}

	_appendMessage(role, content) {
		const cls = role === "User" ? "ai-chat-msg-user" : "ai-chat-msg-assistant";
		const $msg = $(`<div class="ai-chat-msg ${cls}"></div>`);
		const $bubble = $(`<div class="ai-chat-bubble"></div>`);
		this._setBubbleText($bubble, content || "");
		$msg.append($bubble);
		this.$messages.append($msg);
		this._scroll();
		return $bubble;
	}

	_appendDelta(text) {
		if (!this.assistantBubble) {
			this._clearStatus();
			this.assistantBubble = this._appendMessage("Assistant", "");
			this.assistantBubble.data("raw", "");
		}
		const raw = (this.assistantBubble.data("raw") || "") + text;
		this.assistantBubble.data("raw", raw);
		this._setBubbleText(this.assistantBubble, raw);
		this._scroll();
	}

	_setBubbleText($bubble, text) {
		// Escape, then keep line breaks. (Rich markdown is a later polish; escaping
		// here means model output can never inject markup into the user's session.)
		const html = frappe.utils.escape_html(text || "").replace(/\n/g, "<br>");
		$bubble.html(html);
	}

	_renderEmpty() {
		this.$messages.html(`
			<div class="ai-chat-empty">
				<div class="ai-chat-empty-title">${__("Ask about your ERPNext data")}</div>
				<div class="ai-chat-empty-sub text-muted">${__("Read-only. Answers respect your permissions.")}</div>
				<div class="ai-chat-examples">
					<button class="ai-chat-example btn btn-xs" type="button">${__("Summarize this record")}</button>
					<button class="ai-chat-example btn btn-xs" type="button">${__("List my recent AP invoices")}</button>
					<button class="ai-chat-example btn btn-xs" type="button">${__("What's the balance for this vendor?")}</button>
				</div>
			</div>
		`);
		this.$messages.find(".ai-chat-example").on("click", (e) => {
			this.$input.val($(e.currentTarget).text());
			this._autosize();
			this.$input.trigger("focus");
		});
	}

	_dismissEmpty() {
		this.$messages.find(".ai-chat-empty").remove();
	}

	// --- helpers -------------------------------------------------------------
	_showStatus(text) {
		this.$status.text(text).attr("hidden", null);
		this._scroll();
	}

	_clearStatus() {
		this.$status.text("").attr("hidden", "");
	}

	_setComposerEnabled(enabled) {
		this.$input.prop("disabled", !enabled);
		this.$send.prop("disabled", !enabled);
	}

	_autosize() {
		const el = this.$input.get(0);
		if (!el) return;
		el.style.height = "auto";
		el.style.height = Math.min(el.scrollHeight, 120) + "px";
		this.$send.prop("disabled", this.sending || !(this.$input.val() || "").trim());
	}

	_lastUserMessage() {
		const $u = this.$messages.find(".ai-chat-msg-user .ai-chat-bubble").last();
		return $u.length ? $u.text() : null;
	}

	_scroll() {
		this.$messages.scrollTop(this.$messages.get(0).scrollHeight);
	}

	_errMessage(e) {
		const m = e?.message || e?._server_messages || e?.responseJSON?.message;
		if (typeof m === "string" && m.trim()) {
			try {
				const parsed = JSON.parse(m);
				if (Array.isArray(parsed) && parsed.length) return JSON.parse(parsed[0]).message || parsed[0];
			} catch (_) {
				return m;
			}
		}
		return __("Could not reach the AI service.");
	}

	destroy() {
		$(document).off("keydown.aichatpanel", this._key);
		this.stream?.stop();
		this.context?.destroy();
		this.$el.remove();
	}
}
