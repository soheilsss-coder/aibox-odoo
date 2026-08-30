"""
Soup training-data export (roadmap #58, checklist item 1: Context
Firewall before company data reaches a Soup training file) - run with:
  /opt/odoo/odoo-bin shell -c /opt/odoo.conf -d company_ai < 21_soup_export_training_data.py

WHAT THIS DOES: reads every company.document the CURRENT shell env can
see, reuses the exact same text-extraction path as the RAG indexer
(ai_rag's _rag_extract_text, itself the same OCR/unstructured backends
read_attached_file uses - see ai_rag/models/rag_index.py so a document
reads identically everywhere), then runs that text through the SAME
scrub_value() used by recall_memory / read_attached_file / the audit
log (ai_business_tools/models/context_firewall.py) - NOT a separate,
easier-to-drift copy of the denylist. Writes one JSONL line per
document to OUT_PATH.

WHAT THIS DELIBERATELY DOES NOT DO:
  - It does not decide what a good fine-tuning objective is. Each JSONL
    line is {"document_name", "scrubbed_text"} - raw scrubbed source
    text, not an instruction/response pair. Turning this into an
    actual `soup.yaml` `data:` file (chat turns, or whatever the
    template needs) is a human curation step, on purpose - Soup
    fine-tuning on raw dumped text with no curation is a different
    (and worse) failure mode than the one this script exists to guard
    against.
  - It does not run inside the Incus container (see 22_soup_train_
    isolated.sh for that) - it needs direct Odoo ORM access to read
    company.document, which only exists on the Odoo host, so the
    scrubbing has to happen HERE, before anything crosses into the
    training container.
  - It does not touch ai.document.chunk (the RAG vector store) at all -
    reads company.document directly so the exact same firewall applies
    whether or not RAG has indexed a given document yet.

HONEST LIMITATION: scrub_value() is the same denylist +
long-token/card-number regex used everywhere else in this project (see
that file's own docstring for what it does and does not catch) - this
script does not add a second, stricter pass. If a document's secret
doesn't match that denylist's shape, it will not be caught here
either. This step is "don't let a KNOWN secret shape into the training
file", not "guarantee no sensitive information ever reaches Soup".
"""

import json
import os
import sys

from odoo.addons.ai_business_tools.models.context_firewall import scrub_value

OUT_PATH = os.environ.get(
    "SOUP_EXPORT_PATH", "/opt/soup-workspace/data/company_docs_scrubbed.jsonl"
)

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

# sudo() here is read-only and deliberate: an export step run by an
# operator needs every document regardless of who owns/scoped it, the
# same way the daily RAG catch-up cron does (see ai_rag/models/
# rag_index.py's cron_reindex_stale_documents) - this is an offline
# admin tool, not a path a chat user's own env ever reaches.
documents = env["company.document"].sudo().search([])

written = 0
skipped_empty = 0
skipped_error = 0

with open(OUT_PATH, "w", encoding="utf-8") as f:
    for doc in documents:
        try:
            raw_text = ((doc.description or "") + "\n\n" + doc._rag_extract_text()).strip()
        except Exception as exc:  # noqa: BLE001 - one bad file must not kill the export
            print(f"  [skip] {doc.name!r}: extraction failed ({exc})")
            skipped_error += 1
            continue

        if not raw_text:
            skipped_empty += 1
            continue

        scrubbed = scrub_value(raw_text)
        f.write(json.dumps({
            "document_name": doc.name,
            "scrubbed_text": scrubbed,
        }, ensure_ascii=False) + "\n")
        written += 1

print("")
print(f"Wrote {written} scrubbed document(s) to {OUT_PATH}")
print(f"Skipped: {skipped_empty} empty, {skipped_error} extraction errors")
print("")
print("NEXT STEP (manual, on purpose): curate this into soup.yaml's")
print("actual `data:` format for your chosen template before")
print("22_soup_train_isolated.sh - this file is scrubbed SOURCE text,")
print("not ready-to-train examples.")

if written == 0:
    print("\nNothing was written - nothing to curate. Exiting non-zero.")
    sys.exit(1)
