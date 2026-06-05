#!/usr/bin/env bash
cd "$HOME/frappe-bench"
./env/bin/python - <<'PY'
from erpnext.accounts import ap_closed_loop
print("ap_closed_loop OK:", ap_closed_loop.__file__)
from erpnext.accounts.ap_closed_loop import walking_skeleton
print("walking_skeleton OK:", walking_skeleton.__file__)
import erpnext.accounts.doctype.document_capture.document_capture as aic
print("document_capture OK:", aic.__file__)
print("MOCK_PAYMENT_PREFIX:", aic.MOCK_PAYMENT_PREFIX)
PY
