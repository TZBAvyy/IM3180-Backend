from mysql.connector import pooling
import os

# --- Database pooling setup  ---
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "autocommit": True,
}

# --- .env Validation check ---

for k in ("host","user","password","database"):
    if not DB_CONFIG.get(k):
        raise RuntimeError(f"Missing env var {k}")

pool = pooling.MySQLConnectionPool(pool_name="authpool", pool_size=5, **DB_CONFIG)

# --- DB Connection Dependency ---

def get_db():
    conn = pool.get_connection()
    try:
        yield conn
    finally:
        conn.close()