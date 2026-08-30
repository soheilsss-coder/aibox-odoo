# Product Architecture v33

```text
Browser / Buzz / Telegram / future channels
                    |
              Identity Layer
                    |
          AI Control Plane Gateway
                    |
     Authorization: RBAC + ABAC + FGA
                    |
             Capability Registry
                    |
              Risk / Approval
                    |
             Tool Gateway
                    |
        +-----------+-----------+
        |                       |
 Business Action Adapters   Generic READ discovery
        |                       |
        +-----------+-----------+
                    |
              ERP Core Adapter
                    |
                  ERP

Event Outbox -> Workflow / Notification / Calendar / Audit / Buzz / Telegram / Memory / RAG

Memory -> ORM enterprise store -> optional MemoryCore enrichment
RAG -> async index job -> embedding -> pgvector, after ACL filtering
Models -> Model Registry -> Router -> vLLM / future providers
Hermes -> MCP bridge -> policy-aware chat only
```

### Security invariants
1. No product-facing generic ORM write.
2. Generic RPC is disabled unless explicitly enabled for internal/debug use.
3. Browser sessions are HttpOnly cookies; service keys are not returned by login.
4. AI capability selection never bypasses authorization.
5. Odoo ACL/Record Rules remain the final ERP enforcement layer.
6. RAG filters documents before vector search.
7. MemoryCore never decides visibility.
8. Temporary/delegated access cannot grant arbitrary technical groups.
9. Approval target/policy is integrity-protected and rechecked at commit time.
10. New Odoo modules are discovered automatically, but sensitive write capabilities require reviewed adapters.
