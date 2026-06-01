// Copyright (c) 2026, NexeraDigital and contributors
// For license information, please see license.txt

/**
 * Live capture of the current desk context as a *hint*.
 *
 * Subscribes to `frappe.router.on("change")` (frappe.router is an EventEmitter —
 * router.js:692; emits "change" on every route render — router.js:151) and reads
 * `frappe.get_route()` → ["Form", dt, name] / ["List", dt, "List"] /
 * ["Workspaces", name]. On a Form it reads identity (`cur_frm.doctype`/`docname`)
 * only. The hint {doctype,name,view,filters} is the ONLY thing sent to the server,
 * which re-validates + re-fetches under the user's permissions (context.py). The
 * browser's field values are never trusted as authority.
 */

export class ContextTracker {
	constructor(onChange) {
		this.onChange = onChange; // fn(hint|null)
		this.pinned = null; // frozen hint while pinned
		this.current = null; // last captured hint
		this.cleared = false; // transient: dropped until next route change
		this._handler = () => this.refresh();
		// .off before .on so re-construction never double-subscribes (list_view.js:1746 convention).
		frappe.router.off("change", this._handler);
		frappe.router.on("change", this._handler);
		this.refresh();
	}

	destroy() {
		frappe.router.off("change", this._handler);
	}

	get() {
		if (this.pinned) return this.pinned;
		return this.cleared ? null : this.current;
	}

	isPinned() {
		return !!this.pinned;
	}

	pin() {
		this.pinned = this.current;
		this.onChange(this.get());
	}

	unpin() {
		this.pinned = null;
		this.refresh();
	}

	clear() {
		// Drop the hint now; the next navigation re-captures it.
		this.pinned = null;
		this.cleared = true;
		this.onChange(null);
	}

	refresh() {
		if (this.pinned) return; // frozen — navigation must not change a pinned context
		this.cleared = false;
		this.current = this._capture();
		this.onChange(this.get());
	}

	_capture() {
		const route = frappe.get_route() || [];
		const view = route[0];
		if (view === "Form" && route[1] && route[2]) {
			// Identity only; field values are not captured (server re-fetches them).
			return { doctype: route[1], name: route[2], view: "Form" };
		}
		if (view === "List" && route[1]) {
			let filters = null;
			try {
				filters = window.cur_list?.get_filters_for_args?.() || null;
			} catch (e) {
				filters = null;
			}
			return { doctype: route[1], view: "List", filters };
		}
		if (view === "Workspaces" && route[1]) {
			return { name: route[1], view: "Workspaces" };
		}
		return null;
	}

	// Human label for the chip, e.g. "Purchase Invoice ACC-PINV-0001".
	static label(hint) {
		if (!hint) return null;
		if (hint.view === "Form") return `${__(hint.doctype)} ${hint.name}`;
		if (hint.view === "List") {
			const n = hint.filters && Object.keys(hint.filters).length;
			return n ? __("{0} (filtered list)", [__(hint.doctype)]) : __("{0} list", [__(hint.doctype)]);
		}
		if (hint.view === "Workspaces") return __("Workspace: {0}", [hint.name]);
		return null;
	}
}
