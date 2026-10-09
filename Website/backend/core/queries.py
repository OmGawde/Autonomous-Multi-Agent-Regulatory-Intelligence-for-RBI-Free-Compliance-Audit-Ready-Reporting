import json
import logging
import uuid
from datetime import datetime
from .database import get_cursor, IS_SQLITE
from psycopg2.extras import register_default_jsonb, execute_values

# Try registering JSONB adapter for psycopg2 if PostgreSQL is active
try:
    register_default_jsonb()
except Exception:
    pass

logger = logging.getLogger(__name__)

def _prepare_query(query: str) -> str:
    """Replaces PostgreSQL %s placeholders with SQLite ? if running SQLite."""
    from .database import IS_SQLITE
    if IS_SQLITE:
        return query.replace("%s", "?")
    return query

def create_loan_application(conn, applicant_name, bank_name, file_path):
    """Inserts a new loan application and returns the created row."""
    from .database import IS_SQLITE
    if IS_SQLITE:
        app_id = str(uuid.uuid4())
        query = """
            INSERT INTO loan_applications (id, applicant_name, bank_name, file_path, status)
            VALUES (?, ?, ?, ?, 'pending')
        """
        try:
            with get_cursor(conn) as cursor:
                cursor.execute(query, (app_id, applicant_name, bank_name, file_path))
                conn.commit()
                
            return get_loan_application(conn, app_id)
        except Exception as e:
            conn.rollback()
            logger.error(f"Error creating loan application (SQLite): {e}")
            raise
    else:
        query = """
            INSERT INTO loan_applications (applicant_name, bank_name, file_path)
            VALUES (%s, %s, %s)
            RETURNING *;
        """
        try:
            with get_cursor(conn) as cursor:
                cursor.execute(query, (applicant_name, bank_name, file_path))
                result = cursor.fetchone()
                conn.commit()
                return dict(result) if result else None
        except Exception as e:
            conn.rollback()
            logger.error(f"Error creating loan application (Postgres): {e}")
            raise

def get_loan_application(conn, application_id):
    """Retrieves a loan application by ID."""
    query = "SELECT * FROM loan_applications WHERE id = %s;"
    query = _prepare_query(query)
    try:
        with get_cursor(conn) as cursor:
            cursor.execute(query, (application_id,))
            result = cursor.fetchone()
            return dict(result) if result else None
    except Exception as e:
        logger.error(f"Error getting loan application: {e}")
        raise

def update_application_status(conn, application_id, status):
    """Updates the status of a loan application."""
    query = """
        UPDATE loan_applications 
        SET status = %s, updated_at = CURRENT_TIMESTAMP 
        WHERE id = %s;
    """
    query = _prepare_query(query)
    try:
        with get_cursor(conn) as cursor:
            cursor.execute(query, (status, application_id))
            conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating application status: {e}")
        raise

def update_applicant_name(conn, application_id, applicant_name):
    """Updates the applicant name of a loan application."""
    query = """
        UPDATE loan_applications 
        SET applicant_name = %s, updated_at = CURRENT_TIMESTAMP 
        WHERE id = %s;
    """
    query = _prepare_query(query)
    try:
        with get_cursor(conn) as cursor:
            cursor.execute(query, (applicant_name, application_id))
            conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating applicant name: {e}")
        raise

def update_bank_name(conn, application_id, bank_name):
    """Updates the bank name of a loan application."""
    query = """
        UPDATE loan_applications 
        SET bank_name = %s, updated_at = CURRENT_TIMESTAMP 
        WHERE id = %s;
    """
    query = _prepare_query(query)
    try:
        with get_cursor(conn) as cursor:
            cursor.execute(query, (bank_name, application_id))
            conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating bank name: {e}")
        raise

def insert_transactions(conn, application_id, transactions):
    """Bulk inserts transaction records for an application."""
    from .database import IS_SQLITE
    if IS_SQLITE:
        query = """
            INSERT INTO transaction_records (id, application_id, date, description, debit, credit, balance)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """
        try:
            with get_cursor(conn) as cursor:
                data = []
                for t in transactions:
                    if t.get('date') is None:
                        continue
                    tx_id = str(uuid.uuid4())
                    data.append((
                        tx_id,
                        application_id,
                        t.get('date'),
                        t.get('description'),
                        t.get('debit'),
                        t.get('credit'),
                        t.get('balance')
                    ))
                if data:
                    cursor.executemany(query, data)
                conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error inserting transactions (SQLite): {e}")
            raise
    else:
        query = """
            INSERT INTO transaction_records (application_id, date, description, debit, credit, balance)
            VALUES %s;
        """
        data = [
            (
                application_id,
                t.get('date'),
                t.get('description'),
                t.get('debit'),
                t.get('credit'),
                t.get('balance')
            )
            for t in transactions
            if t.get('date') is not None
        ]
        if not data:
            logger.warning(f"No valid transaction records found to insert for application: {application_id}")
            return
            
        try:
            with get_cursor(conn) as cursor:
                execute_values(cursor, query, data, page_size=1000)
                conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error inserting transactions (Postgres): {e}")
            raise

def get_transactions(conn, application_id):
    """Retrieves all transaction records for an application ordered by date."""
    query = "SELECT * FROM transaction_records WHERE application_id = %s ORDER BY date ASC;"
    query = _prepare_query(query)
    try:
        with get_cursor(conn) as cursor:
            cursor.execute(query, (application_id,))
            results = cursor.fetchall()
            clean_list = []
            for r in results:
                d = dict(r)
                if 'id' in d:
                    d['id'] = str(d['id'])
                if 'application_id' in d:
                    d['application_id'] = str(d['application_id'])
                d['date'] = str(d['date']) if d.get('date') is not None else ""
                d['description'] = str(d['description']) if d.get('description') is not None else ""
                d['debit'] = float(d['debit']) if d.get('debit') is not None else 0.0
                d['credit'] = float(d['credit']) if d.get('credit') is not None else 0.0
                d['balance'] = float(d['balance']) if d.get('balance') is not None else 0.0
                clean_list.append(d)
            return clean_list
    except Exception as e:
        logger.error(f"Error getting transactions: {e}")
        raise

def create_loan_result(conn, application_id, result):
    """Inserts a new loan result and returns the created row."""
    from .database import IS_SQLITE
    if IS_SQLITE:
        res_id = str(uuid.uuid4())
        query = """
            INSERT INTO loan_results (
                id, application_id, average_monthly_balance, total_income, 
                total_expenses, debt_to_income_ratio, monthly_obligations, 
                decision, confidence_score, reasoning, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            res_id,
            application_id,
            result.get('average_monthly_balance'),
            result.get('total_income'),
            result.get('total_expenses'),
            result.get('debt_to_income_ratio'),
            result.get('monthly_obligations'),
            result.get('decision'),
            result.get('confidence_score'),
            result.get('reasoning'),
            json.dumps(result.get('metadata', {}), default=str)
        )
        try:
            with get_cursor(conn) as cursor:
                cursor.execute(query, params)
                conn.commit()
            return get_loan_result(conn, application_id)
        except Exception as e:
            conn.rollback()
            logger.error(f"Error creating loan result (SQLite): {e}")
            raise
    else:
        query = """
            INSERT INTO loan_results (
                application_id, average_monthly_balance, total_income, 
                total_expenses, debt_to_income_ratio, monthly_obligations, 
                decision, confidence_score, reasoning, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *;
        """
        params = (
            application_id,
            result.get('average_monthly_balance'),
            result.get('total_income'),
            result.get('total_expenses'),
            result.get('debt_to_income_ratio'),
            result.get('monthly_obligations'),
            result.get('decision'),
            result.get('confidence_score'),
            result.get('reasoning'),
            json.dumps(result.get('metadata', {}), default=str)
        )
        try:
            with get_cursor(conn) as cursor:
                cursor.execute(query, params)
                created_row = cursor.fetchone()
                conn.commit()
                return dict(created_row) if created_row else None
        except Exception as e:
            conn.rollback()
            logger.error(f"Error creating loan result (Postgres): {e}")
            raise

def get_loan_result(conn, application_id):
    """Retrieves the loan result for an application."""
    query = "SELECT * FROM loan_results WHERE application_id = %s;"
    query = _prepare_query(query)
    try:
        with get_cursor(conn) as cursor:
            cursor.execute(query, (application_id,))
            result = cursor.fetchone()
            if result:
                res_dict = dict(result)
                if isinstance(res_dict.get('metadata'), str):
                    try:
                        res_dict['metadata'] = json.loads(res_dict['metadata'])
                    except:
                        pass
                return res_dict
            return None
    except Exception as e:
        logger.error(f"Error getting loan result: {e}")
        raise

def get_all_applications(conn):
    """Retrieves all loan applications with optional loan results ordered by creation date."""
    from .database import IS_SQLITE
    if IS_SQLITE:
        query = """
            SELECT 
                la.id, 
                la.applicant_name, 
                la.bank_name, 
                la.status, 
                la.created_at AS created_at,
                lr.decision,
                lr.confidence_score,
                lr.average_monthly_balance
            FROM loan_applications la
            LEFT JOIN loan_results lr ON la.id = lr.application_id
            ORDER BY la.created_at DESC;
        """
    else:
        query = """
            SELECT 
                la.id, 
                la.applicant_name, 
                la.bank_name, 
                la.status, 
                la.created_at AT TIME ZONE 'UTC' AS created_at,
                lr.decision,
                lr.confidence_score,
                lr.average_monthly_balance
            FROM loan_applications la
            LEFT JOIN loan_results lr ON la.id = lr.application_id
            ORDER BY la.created_at DESC;
        """
    try:
        with get_cursor(conn) as cursor:
            cursor.execute(query)
            results = cursor.fetchall()
            return [dict(r) for r in results]
    except Exception as e:
        logger.error(f"Error getting all applications: {e}")
        raise
