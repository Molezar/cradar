import os
from config import Config
from database.database import get_db

MIGRATIONS_DIR = "migrations"

# === Вычисляем путь лога миграции для каждой среды ===
if Config.ENV == "PROD":
    MIGRATIONS_LOG = "/data/prod_applied_migrations.txt"
elif Config.ENV == "STAG":
    MIGRATIONS_LOG = "/data/stag_applied_migrations.txt"
else:
    MIGRATIONS_LOG = "database/applied_migrations.txt"

# ✅ Ensure directory exists for migration log
log_dir = os.path.dirname(MIGRATIONS_LOG)
os.makedirs(log_dir, exist_ok=True)

# ✅ Ensure file exists
if not os.path.exists(MIGRATIONS_LOG):
    open(MIGRATIONS_LOG, "w").close()


def get_applied_migrations():
    if not os.path.exists(MIGRATIONS_LOG):
        return set()
    with open(MIGRATIONS_LOG, "r") as f:
        return set(line.strip() for line in f)

def save_applied_migration(name):
    with open(MIGRATIONS_LOG, "a") as f:
        f.write(name + "\n")

def run_migrations():
    applied = get_applied_migrations()
    migration_files = sorted(f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql"))

    conn = get_db()
    print("MIGRATION DB PATH:", Config.DB_PATH)
    cursor = conn.cursor()

    for filename in migration_files:
        if filename in applied:
            continue

        path = os.path.join(MIGRATIONS_DIR, filename)
        with open(path, "r", encoding="utf-8") as f:
            sql = f.read()
            try:
                cursor.executescript(sql)
                conn.commit()
                print(f"✅ Applied: {filename}")
                save_applied_migration(filename)
            except Exception as e:
                print(f"❌ Failed: {filename}\n{e}")
                conn.rollback()

    conn.close()
    print("🚀 Migrations finished.")

if __name__ == "__main__":
    run_migrations()