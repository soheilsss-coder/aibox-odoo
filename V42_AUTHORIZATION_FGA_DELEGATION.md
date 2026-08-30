# v42 — Authorization / FGA / Delegation Consolidation

## Invariants

1. Temporary/delegated access MUST NOT mutate `res.groups.users`.
2. A grant is an authorization fact evaluated by `ai.control.authorization`.
3. Delegation cannot launder authority: the delegator must hold the delegated role permanently.
4. Resource-scoped grants apply only to the declared model/id.
5. FGA relations are time-bounded and fail closed outside their validity window.
6. Authorization combines permanent groups, valid grants, policy scope, and FGA relations.

## Remaining certification boundary

This release is a source-level consolidation. Runtime multi-worker, approval, and end-to-end module certification remain required before Production Certified status.
