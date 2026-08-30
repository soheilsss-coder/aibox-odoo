# Licensing Notes (roadmap #56)

> **This is not legal advice.** It is a summary of what is verifiably
> true about the licenses actually declared in this codebase, written
> so that a real IP/contract lawyer has less groundwork to do before
> reviewing your customer sales agreement - it does not replace that
> review. Roadmap item #56 itself says this explicitly: get a real
> lawyer before any commercial delivery. Nothing below should be
> treated as a substitute for that.

## What license each part of this project actually declares

| Component | License (as declared in the code) | Where |
|---|---|---|
| Odoo Community core | LGPL-3 | upstream, not in this repo |
| `ai_gateway` | LGPL-3 | `custom_addons/ai_gateway/__manifest__.py` |
| `ai_business_tools` | LGPL-3 | `custom_addons/ai_business_tools/__manifest__.py` |
| `ai_rag` | LGPL-3 | `custom_addons/ai_rag/__manifest__.py` |
| `ai_semantic_api` | LGPL-3 | `custom_addons/ai_semantic_api/__manifest__.py` |
| `ai_debrand` | LGPL-3 | `custom_addons/ai_debrand/__manifest__.py` |
| `company_ai_demo` | LGPL-3 | `custom_addons/company_ai_demo/__manifest__.py` |
| `frontend/` (React app) | **not declared** - `frontend/package.json` has no `"license"` field | `frontend/package.json` |
| Soup (roadmap #58, optional) | Apache-2.0 | upstream: `github.com/MakazhanAlpamys/Soup` |
| Buzz (roadmap #59, optional) | Apache-2.0 | upstream: `github.com/block/buzz` |

## The one technical point worth understanding before talking to a lawyer

All six custom Odoo modules are declared LGPL-3 - matching Odoo
Community's own core license, which is the normal/expected choice for
an addon that loads into and depends on LGPL-3 code. A practical
consequence of LGPL-3 (this is a description of what the license
text says, not legal advice about how it applies to your specific
contract): if you hand a customer's IT department a running install of
these modules, the Python/XML source is not compiled away - it is
readable on disk, and LGPL-3 requires that a recipient of the work be
able to obtain, modify, and reuse that source. Concretely, this
generally means you can charge for the hardware, the install/setup
labor, ongoing support, and hosting - but you cannot contractually
prevent the customer from reading, modifying, or removing the addon
code you delivered to them, once delivered.

The `frontend/` React app is architecturally separate on purpose
(roadmap #43/#44: it only ever talks to `/api/*` over HTTP, never
imports anything from Odoo, never runs inside the Odoo process). That
separation is also why it was deliberately NOT given a manifest
`"license": "LGPL-3"` line the way the six Odoo modules were - being a
standalone codebase that merely calls a network API, rather than code
that loads into/extends the LGPL-3-licensed Odoo core, is generally
understood to sit outside the kind of "combined work" LGPL-3's
copyleft terms are triggered by. **This specific boundary argument has
not been reviewed by a lawyer** - it is exactly the kind of question
worth putting in front of one before it matters, not after. Until you
do, `frontend/package.json` still has no `"license"` field at all;
picking one (proprietary/closed source is the simplest default for a
product you're selling) is a five-minute fix once you've had that
conversation.

## Things to flag for the lawyer conversation, not to solve here

- **Never mix in Odoo Enterprise Edition modules.** Enterprise modules
  use a different, proprietary Odoo license, not LGPL-3. Accidentally
  depending on one (a common real mistake - some Enterprise modules
  have innocuous-sounding names) would break the licensing model this
  entire project's Community-only architecture assumes.
- **Third-party model weights** (the Qwen checkpoints referenced in
  `01_setup_base.sh`/`09_setup_soup_finetune.sh`) carry their own
  model license, separate from the code license question above - check
  the specific checkpoint's license page before redistributing model
  weights themselves (as opposed to just running them as a service).
- **The actual customer sales/support contract** - the wording that
  says what the customer is and isn't allowed to do, what support you
  owe them, and what happens if they modify the code you delivered -
  is a separate document from any of the above and is exactly what
  roadmap item #56 said needs a real lawyer, not this file.
