// Copyright (c) 2026, NexeraDigital and contributors
// For license information, please see license.txt

/**
 * Subscribe to a turn's realtime channel and drive UI callbacks.
 *
 * The backend publishes to `ai_chat:<conversation>` on the user's room
 * (agent.py): {type:"status"|"delta"|"done"|"error", …}. `frappe.realtime` is the
 * Socket.IO client (socketio_client.js:223) with `.on/.off(event, cb)`. We
 * unsubscribe on `done`/`error` to avoid handler leaks (call_popup.js:88-101
 * cleanup convention).
 */

export class TurnStream {
	constructor(conversation, handlers) {
		this.event = `ai_chat:${conversation}`;
		this.handlers = handlers || {};
		this._cb = (data) => this._dispatch(data);
		frappe.realtime.on(this.event, this._cb);
	}

	_dispatch(data) {
		const type = data && data.type;
		if (type === "status") {
			this.handlers.onStatus?.(data.text);
		} else if (type === "delta") {
			this.handlers.onDelta?.(data.text);
		} else if (type === "done") {
			this.handlers.onDone?.(data);
			this.stop();
		} else if (type === "error") {
			this.handlers.onError?.(data.text);
			this.stop();
		}
	}

	stop() {
		if (this._cb) {
			frappe.realtime.off(this.event, this._cb);
			this._cb = null;
		}
	}
}
