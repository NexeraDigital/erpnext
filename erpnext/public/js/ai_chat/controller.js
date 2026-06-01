// Copyright (c) 2026, NexeraDigital and contributors
// For license information, please see license.txt

import { Launcher } from "./launcher";
import { Panel } from "./panel";

/**
 * Wires the persistent launcher to the slide-over panel. One instance is mounted
 * on `document.body` for the whole desk session (see ai_chat.bundle.js), so the
 * conversation state survives SPA navigation.
 */
export class AIChatController {
	constructor() {
		this.panel = new Panel();
		this.launcher = new Launcher(() => this.panel.toggle());
		this.panel.onOpenChange = (open) => this.launcher.setActive(open);
	}

	destroy() {
		this.launcher.destroy();
		this.panel.destroy();
	}
}
