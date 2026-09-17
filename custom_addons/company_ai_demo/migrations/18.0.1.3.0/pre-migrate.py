"""Prepare encrypted memory rows for the scoped-key uniqueness constraint."""


def migrate(cr, version):
    if not version:
        return
    # create_memory now has an explicit upsert contract. Keep the newest row
    # for legacy duplicates before Odoo creates the SQL unique constraint.
    cr.execute(
        """
        DELETE FROM ai_agent_memory_record older
        USING ai_agent_memory_record newer
        WHERE older.id < newer.id
          AND older.user_id = newer.user_id
          AND older.company_id = newer.company_id
          AND older.scope = newer.scope
          AND older.key = newer.key
        """
    )
