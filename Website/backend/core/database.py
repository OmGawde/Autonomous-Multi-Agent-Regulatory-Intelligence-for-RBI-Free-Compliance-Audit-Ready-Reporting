import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from .config import settings
import logging
import os

logger = logging.getLogger(__name__)

# Global flag to track connection type
IS_SQLITE = False

def get_connection():
    """Creates and returns a database connection (PostgreSQL or SQLite fallback)."""
    global IS_SQLITE
    
    # Check if DATABASE_URL is set and looks like PostgreSQL
    db_url = settings.DATABASE_URL
    is_pg = db_url and (db_url.startswith("postgresql://") or db_url.startswith("postgres://"))
    
    if is_pg:
        try:
            conn = psycopg2.connect(db_url)
            conn.autocommit = False
            IS_SQLITE = False
            return conn
        except Exception as e:
            logger.warning(f"PostgreSQL connection failed: {e}. Falling back to SQLite.")
            
    # SQLite fallback
    try:
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "loan_processing.db")
        conn = sqlite3.connect(db_path, timeout=20.0)
        conn.row_factory = sqlite3.Row
        IS_SQLITE = True
        return conn
    except Exception as e:
        logger.error(f"Error connecting to SQLite: {e}")
        raise

@contextmanager
def get_cursor(conn):
    """Context manager yielding a dictionary-like cursor for PostgreSQL/SQLite."""
    global IS_SQLITE
    if IS_SQLITE:
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()
    else:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cursor
        finally:
            cursor.close()

def init_db():
    """Initializes the database schema for both PostgreSQL and SQLite."""
    conn = get_connection()
    global IS_SQLITE
    try:
        if IS_SQLITE:
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
            except Exception as wal_err:
                logger.warning(f"Could not enable WAL mode: {wal_err}")
        with get_cursor(conn) as cursor:
            if IS_SQLITE:
                # SQLite DDL
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS loan_applications (
                        id TEXT PRIMARY KEY,
                        applicant_name TEXT NOT NULL,
                        bank_name TEXT NOT NULL,
                        status TEXT DEFAULT 'pending',
                        file_path TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS transaction_records (
                        id TEXT PRIMARY KEY,
                        application_id TEXT REFERENCES loan_applications(id),
                        date TEXT,
                        description TEXT,
                        debit REAL,
                        credit REAL,
                        balance REAL
                    );
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS loan_results (
                        id TEXT PRIMARY KEY,
                        application_id TEXT REFERENCES loan_applications(id) UNIQUE,
                        average_monthly_balance REAL,
                        total_income REAL,
                        total_expenses REAL,
                        debt_to_income_ratio REAL,
                        monthly_obligations REAL,
                        decision TEXT,
                        confidence_score REAL,
                        reasoning TEXT,
                        metadata TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
            else:
                # PostgreSQL DDL
                cursor.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS loan_applications (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        applicant_name VARCHAR(255) NOT NULL,
                        bank_name VARCHAR(100) NOT NULL,
                        status VARCHAR(50) DEFAULT 'pending',
                        file_path TEXT,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    );
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS transaction_records (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        application_id UUID REFERENCES loan_applications(id),
                        date DATE,
                        description TEXT,
                        debit FLOAT,
                        credit FLOAT,
                        balance FLOAT
                    );
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS loan_results (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        application_id UUID REFERENCES loan_applications(id) UNIQUE,
                        average_monthly_balance FLOAT,
                        total_income FLOAT,
                        total_expenses FLOAT,
                        debt_to_income_ratio FLOAT,
                        monthly_obligations FLOAT,
                        decision VARCHAR(50),
                        confidence_score FLOAT,
                        reasoning TEXT,
                        metadata JSONB,
                        created_at TIMESTAMP DEFAULT NOW()
                    );
                """)
            conn.commit()
            logger.info("Database initialized successfully.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Error initializing database: {e}")
        raise
    finally:
        close_connection(conn)

def close_connection(conn):
    """Closes connection safely."""
    if conn:
        conn.close()
