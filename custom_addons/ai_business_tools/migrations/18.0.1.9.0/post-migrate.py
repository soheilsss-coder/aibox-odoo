"""18.0.1.9.0: put the cron service account in the new
ai_gateway.group_ai_automation group (noupdate data never re-runs on
upgrade, so EXISTING appliances would keep a service user without the
minimal maintenance grants the 18.0.1.9.0 ACLs provide). Idempotent."""
def migrate(cr, version):
    cr.execute("""
        INSERT INTO res_groups_users_rel (gid, uid)
        SELECT g.id, u.id
        FROM ir_module_module m,
             ir_model_data d,
             res_groups g,
             res_users u
        WHERE m.name = 'ai_gateway' AND m.state = 'installed'
          AND d.module = m.name AND d.name = 'group_ai_automation'
          AND d.model = 'res.groups' AND d.res_id = g.id
          AND u.login = 'ai-automation@service.local'
        ON CONFLICT DO NOTHING
    """)
