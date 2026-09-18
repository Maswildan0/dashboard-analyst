class SourceReadOnlyRouter:
    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == 'source':
            return False
        return None

    def db_for_write(self, model, **hints):
        instance = hints.get('instance')
        if instance is not None and instance._state.db == 'source':
            raise RuntimeError('Writes to the MySQL migration source are prohibited.')
        return None
