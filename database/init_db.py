from pathlib import Path
import sqlite3


def main():
    # Paths
    base_dir = Path(__file__).resolve().parent
    schema_path = base_dir / "schema.sql"
    db_path = base_dir / "app.db"

    # Connect to SQLite database (creates app.db if it does not exist)
    conn = sqlite3.connect(db_path)

    try:
        # Turn on foreign key support in SQLite
        conn.execute("PRAGMA foreign_keys = ON;")

        # Read schema.sql
        schema_sql = schema_path.read_text(encoding="utf-8")

        # Execute the full schema
        conn.executescript(schema_sql)

        print(f"Database initialized successfully at: {db_path}")

    except Exception as e:
        print("Failed to initialize database.")
        print(f"Error: {e}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()