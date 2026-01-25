"""
SQLite Database Module - Manages compliance data persistence
Stores execution history, results, and enables trend analysis
"""

import json
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class ComplianceDatabase:
    """SQLite database for compliance monitoring"""
    
    def __init__(self, db_path: str = "data/compliance.db"):
        """
        Initialize database connection
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = None
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        try:
            self.connection = sqlite3.connect(str(self.db_path))
            self.connection.row_factory = sqlite3.Row
            cursor = self.connection.cursor()
            
            # Executions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS executions (
                    execution_id TEXT PRIMARY KEY,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    total_duration_ms INTEGER,
                    rss_entries_count INTEGER,
                    new_guidelines_count INTEGER,
                    guidelines_stored INTEGER,
                    policy_clauses_count INTEGER,
                    gaps_identified INTEGER,
                    covered_count INTEGER,
                    outdated_count INTEGER,
                    missing_count INTEGER,
                    overall_status TEXT,
                    status TEXT CHECK(status IN ('SUCCESS', 'FAILED')),
                    error_message TEXT
                )
            ''')
            
            # Compliance Results table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS compliance_results (
                    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    execution_id TEXT NOT NULL,
                    guideline_id INTEGER,
                    guideline_title TEXT,
                    compliance_status TEXT CHECK(compliance_status IN ('COVERED', 'OUTDATED', 'MISSING')),
                    keyword_count INTEGER,
                    match_percentage REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(execution_id) REFERENCES executions(execution_id)
                )
            ''')
            
            # Daily Trends table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_trends (
                    trend_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE UNIQUE,
                    executions_count INTEGER,
                    covered_count INTEGER,
                    outdated_count INTEGER,
                    missing_count INTEGER,
                    avg_coverage_percentage REAL,
                    total_guidelines INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Execution Log table for detailed tracing
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS execution_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    execution_id TEXT NOT NULL,
                    step_number INTEGER,
                    step_name TEXT,
                    duration_ms INTEGER,
                    status TEXT CHECK(status IN ('SUCCESS', 'FAILED')),
                    message TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(execution_id) REFERENCES executions(execution_id)
                )
            ''')
            
            # Create indexes for faster queries
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_execution_timestamp ON executions(timestamp DESC)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_execution_status ON executions(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_results_execution ON compliance_results(execution_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trends_date ON daily_trends(date DESC)')
            
            self.connection.commit()
            logger.info(f"Database initialized at: {self.db_path}")
        
        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")
            raise
    
    def insert_execution(self, execution_id: str, data: Dict) -> bool:
        """
        Insert execution record
        
        Args:
            execution_id: Unique execution identifier
            data: Dictionary with execution metrics
        
        Returns:
            True if successful
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                INSERT INTO executions (
                    execution_id, total_duration_ms, rss_entries_count,
                    new_guidelines_count, guidelines_stored, policy_clauses_count,
                    gaps_identified, covered_count, outdated_count, missing_count,
                    overall_status, status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                execution_id,
                data.get('total_duration_ms', 0),
                data.get('rss_entries_count', 0),
                data.get('new_guidelines_count', 0),
                data.get('guidelines_stored', 0),
                data.get('policy_clauses_count', 0),
                data.get('gaps_identified', 0),
                data.get('covered_count', 0),
                data.get('outdated_count', 0),
                data.get('missing_count', 0),
                data.get('overall_status', 'Not Evaluated'),
                data.get('status', 'SUCCESS'),
                data.get('error_message', None)
            ))
            self.connection.commit()
            logger.info(f"Execution {execution_id} inserted successfully")
            return True
        
        except sqlite3.Error as e:
            logger.error(f"Error inserting execution: {e}")
            return False
    
    def insert_compliance_results(self, execution_id: str, results: List[Dict]) -> bool:
        """
        Insert compliance results for execution
        
        Args:
            execution_id: Unique execution identifier
            results: List of compliance result dictionaries
        
        Returns:
            True if successful
        """
        try:
            cursor = self.connection.cursor()
            for result in results:
                cursor.execute('''
                    INSERT INTO compliance_results (
                        execution_id, guideline_id, guideline_title,
                        compliance_status, keyword_count, match_percentage
                    ) VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    execution_id,
                    result.get('guideline_id'),
                    result.get('guideline_title'),
                    result.get('compliance_status'),
                    result.get('keyword_count'),
                    result.get('match_percentage', 0)
                ))
            self.connection.commit()
            logger.info(f"Inserted {len(results)} compliance results")
            return True
        
        except sqlite3.Error as e:
            logger.error(f"Error inserting compliance results: {e}")
            return False
    
    def insert_step_log(self, execution_id: str, step: int, name: str, 
                       duration_ms: float, status: str, message: str = "") -> bool:
        """
        Insert step execution log
        
        Args:
            execution_id: Unique execution identifier
            step: Step number
            name: Step name
            duration_ms: Step duration in milliseconds
            status: SUCCESS or FAILED
            message: Optional message
        
        Returns:
            True if successful
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                INSERT INTO execution_logs (
                    execution_id, step_number, step_name,
                    duration_ms, status, message
                ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (execution_id, step, name, int(duration_ms), status, message))
            self.connection.commit()
            return True
        
        except sqlite3.Error as e:
            logger.error(f"Error inserting step log: {e}")
            return False
    
    def update_daily_trends(self, execution_id: str) -> bool:
        """
        Update or insert daily trend record
        
        Args:
            execution_id: Unique execution identifier
        
        Returns:
            True if successful
        """
        try:
            cursor = self.connection.cursor()
            
            # Get today's data
            today = datetime.now().date()
            
            # Get execution metrics
            cursor.execute('SELECT * FROM executions WHERE execution_id = ?', (execution_id,))
            exec_row = cursor.fetchone()
            
            if not exec_row:
                return False
            
            covered = exec_row['covered_count']
            outdated = exec_row['outdated_count']
            missing = exec_row['missing_count']
            total = covered + outdated + missing
            
            coverage_pct = (covered / total * 100) if total > 0 else 0
            
            # Check if today's trend exists
            cursor.execute('SELECT trend_id FROM daily_trends WHERE date = ?', (str(today),))
            trend_row = cursor.fetchone()
            
            if trend_row:
                # Update existing
                cursor.execute('''
                    UPDATE daily_trends SET
                    executions_count = executions_count + 1,
                    covered_count = covered_count + ?,
                    outdated_count = outdated_count + ?,
                    missing_count = missing_count + ?,
                    avg_coverage_percentage = (avg_coverage_percentage + ?) / 2,
                    total_guidelines = ?,
                    updated_at = CURRENT_TIMESTAMP
                    WHERE date = ?
                ''', (covered, outdated, missing, coverage_pct, total, str(today)))
            else:
                # Insert new
                cursor.execute('''
                    INSERT INTO daily_trends (
                        date, executions_count, covered_count, outdated_count,
                        missing_count, avg_coverage_percentage, total_guidelines
                    ) VALUES (?, 1, ?, ?, ?, ?, ?)
                ''', (str(today), covered, outdated, missing, coverage_pct, total))
            
            self.connection.commit()
            logger.info(f"Daily trends updated for {today}")
            return True
        
        except sqlite3.Error as e:
            logger.error(f"Error updating trends: {e}")
            return False
    
    def get_execution_history(self, limit: int = 10) -> List[Dict]:
        """Get recent execution history"""
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                SELECT * FROM executions
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        
        except sqlite3.Error as e:
            logger.error(f"Error retrieving execution history: {e}")
            return []
    
    def get_trends(self, days: int = 30) -> List[Dict]:
        """Get trend data for specified days"""
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                SELECT * FROM daily_trends
                WHERE date >= date('now', '-' || ? || ' days')
                ORDER BY date DESC
            ''', (days,))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        
        except sqlite3.Error as e:
            logger.error(f"Error retrieving trends: {e}")
            return []
    
    def get_compliance_summary(self) -> Dict:
        """Get overall compliance summary from database"""
        try:
            cursor = self.connection.cursor()
            
            # Latest execution stats
            cursor.execute('''
                SELECT 
                    SUM(covered_count) as total_covered,
                    SUM(outdated_count) as total_outdated,
                    SUM(missing_count) as total_missing,
                    COUNT(*) as total_executions,
                    AVG(total_duration_ms) as avg_duration_ms
                FROM executions
                WHERE status = 'SUCCESS'
            ''')
            
            row = cursor.fetchone()
            stats = dict(row) if row else {}
            
            # Trend summary
            cursor.execute('''
                SELECT 
                    MAX(avg_coverage_percentage) as max_coverage,
                    MIN(avg_coverage_percentage) as min_coverage,
                    AVG(avg_coverage_percentage) as current_coverage
                FROM daily_trends
            ''')
            
            trend_row = cursor.fetchone()
            if trend_row:
                stats.update({k: v for k, v in dict(trend_row).items() if v is not None})
            
            return stats
        
        except sqlite3.Error as e:
            logger.error(f"Error retrieving summary: {e}")
            return {}
    
    def close(self):
        """Close database connection"""
        if self.connection:
            self.connection.close()
            logger.info("Database connection closed")


def main():
    """Test database initialization"""
    db = ComplianceDatabase()
    
    # Test insertion
    test_execution = {
        'total_duration_ms': 1800,
        'rss_entries_count': 10,
        'new_guidelines_count': 2,
        'guidelines_stored': 2,
        'policy_clauses_count': 5,
        'gaps_identified': 2,
        'covered_count': 0,
        'outdated_count': 0,
        'missing_count': 2,
        'overall_status': 'Not Evaluated',
        'status': 'SUCCESS'
    }
    
    exec_id = f"TEST-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    success = db.insert_execution(exec_id, test_execution)
    
    if success:
        print(f"[SUCCESS] Database test passed")
        print(f"Execution ID: {exec_id}")
    
    db.close()


if __name__ == "__main__":
    main()
