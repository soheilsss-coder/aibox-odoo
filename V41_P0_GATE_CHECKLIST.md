# v41 P0 Gate Checklist

- [x] Generic `/api/rpc` disabled (410)
- [x] Production CORS fails closed
- [x] Browser auth uses HttpOnly `ai_session`
- [x] Session rotation and revocation
- [x] Plaintext API-key field removed from ORM + migration clears legacy secret
- [x] Redis/shared limiter required in production
- [x] Central execution gate remains mandatory for registered operations
- [x] Approval replay goes back through execution gate
- [ ] FGA/delegation engine
- [ ] Durable workflow recovery/compensation/human tasks
- [ ] Full event subscriber matrix
- [ ] SSO/SCIM
- [ ] Customer customization plane
- [ ] Real Purchase/Stock/Accounting/Manufacturing/CRM/HR E2E certification
