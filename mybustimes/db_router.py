class PrimaryReplicaRouter:
    

    SAFE_READ_APPS = [
        "routes",
        "stops",
        "operators",
    ]

    def db_for_read(self, model, **hints):
        if model._meta.app_label in self.SAFE_READ_APPS:
            return "replica"
        return "default"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, **hints):
        return db == "default"
