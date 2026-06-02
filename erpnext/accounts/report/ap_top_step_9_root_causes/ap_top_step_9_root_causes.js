// Copyright (c) 2026, Nexera and Contributors
// License: GNU General Public License v3. See license.txt

/* eslint-disable */
frappe.query_reports["AP Top Step 9 Root Causes"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
	],
};
