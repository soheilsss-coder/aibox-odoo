"""Align seeded model aliases with the native serving units on upgrade."""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE ai_model_profile
           SET endpoint = 'http://127.0.0.1:8002/v1',
               model_id = 'embedding-model'
         WHERE purpose = 'embedding' AND name = 'Qwen3 Embedding'
    """)
    cr.execute("""
        UPDATE ai_model_profile
           SET endpoint = 'http://127.0.0.1:8001/v1'
         WHERE purpose = 'vision' AND name = 'Vision Model'
    """)
    cr.execute("""
        UPDATE ai_model_profile
           SET endpoint = 'http://127.0.0.1:8000/v1',
               model_id = 'local-model',
               supports_streaming = TRUE,
               supports_tools = TRUE
         WHERE purpose = 'chat' AND name = 'Qwen AWQ'
    """)
