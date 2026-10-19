"""Flask factory for explicit migrations; importing it never mutates the schema."""
from cuotago import create_app

def create_maintenance_app():
    return create_app({'AUTO_CREATE_DB': False, 'CHECK_SCHEMA_ON_START': False,
                       'PUSH_SCHEDULER_ENABLED': False})

app = create_maintenance_app()
