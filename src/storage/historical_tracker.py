"""
Historical Tracking Module - Analyzes compliance trends over time
Generates insights and comparisons from database records
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List
from src.storage.compliance_db import ComplianceDatabase

logger = logging.getLogger(__name__)


class HistoricalTracker:
    """Track and analyze historical compliance data"""
    
    def __init__(self, db_path: str = "data/compliance.db"):
        """
        Initialize tracker
        
        Args:
            db_path: Path to SQLite database
        """
        self.db = ComplianceDatabase(db_path)
        self.report = {}
    
    def generate_analytics_report(self, days: int = 30) -> Dict:
        """
        Generate comprehensive analytics report
        
        Args:
            days: Number of days to analyze
        
        Returns:
            Dictionary with analytics data
        """
        logger.info(f"Generating analytics report for last {days} days...")
        
        # Get execution history
        history = self.db.get_execution_history(limit=100)
        trends = self.db.get_trends(days=days)
        summary = self.db.get_compliance_summary()
        
        self.report = {
            "report_generated": datetime.now().isoformat(),
            "analysis_period_days": days,
            "execution_statistics": self._calculate_execution_stats(history),
            "compliance_metrics": self._calculate_compliance_metrics(history),
            "trend_analysis": self._analyze_trends(trends),
            "performance_summary": self._performance_summary(summary),
            "insights": self._generate_insights(history, trends, summary)
        }
        
        logger.info("Analytics report generated successfully")
        return self.report
    
    def _calculate_execution_stats(self, history: List[Dict]) -> Dict:
        """Calculate execution statistics"""
        if not history:
            return {}
        
        total_execs = len(history)
        successful = sum(1 for h in history if h['status'] == 'SUCCESS')
        failed = total_execs - successful
        
        durations = [h['total_duration_ms'] for h in history if h['total_duration_ms']]
        avg_duration = sum(durations) / len(durations) if durations else 0
        
        return {
            "total_executions": total_execs,
            "successful": successful,
            "failed": failed,
            "success_rate_percent": (successful / total_execs * 100) if total_execs > 0 else 0,
            "avg_duration_ms": round(avg_duration, 2),
            "min_duration_ms": min(durations) if durations else 0,
            "max_duration_ms": max(durations) if durations else 0
        }
    
    def _calculate_compliance_metrics(self, history: List[Dict]) -> Dict:
        """Calculate compliance metrics"""
        if not history:
            return {}
        
        total_covered = sum(h.get('covered_count', 0) for h in history)
        total_outdated = sum(h.get('outdated_count', 0) for h in history)
        total_missing = sum(h.get('missing_count', 0) for h in history)
        
        total_gaps = total_covered + total_outdated + total_missing
        
        return {
            "total_covered": total_covered,
            "total_outdated": total_outdated,
            "total_missing": total_missing,
            "total_gaps": total_gaps,
            "covered_percent": (total_covered / total_gaps * 100) if total_gaps > 0 else 0,
            "outdated_percent": (total_outdated / total_gaps * 100) if total_gaps > 0 else 0,
            "missing_percent": (total_missing / total_gaps * 100) if total_gaps > 0 else 0
        }
    
    def _analyze_trends(self, trends: List[Dict]) -> Dict:
        """Analyze trend data"""
        if not trends:
            return {"status": "No trend data available"}
        
        # Sort by date ascending for trend analysis
        sorted_trends = sorted(trends, key=lambda x: x['date'])
        
        latest = sorted_trends[-1] if sorted_trends else {}
        oldest = sorted_trends[0] if sorted_trends else {}
        
        improvement = {
            "covered_change": latest.get('covered_count', 0) - oldest.get('covered_count', 0),
            "coverage_pct_change": latest.get('avg_coverage_percentage', 0) - oldest.get('avg_coverage_percentage', 0)
        }
        
        return {
            "total_days_tracked": len(sorted_trends),
            "latest_date": latest.get('date'),
            "oldest_date": oldest.get('date'),
            "latest_metrics": {
                "date": latest.get('date'),
                "coverage_percent": round(latest.get('avg_coverage_percentage', 0), 2),
                "covered": latest.get('covered_count', 0),
                "outdated": latest.get('outdated_count', 0),
                "missing": latest.get('missing_count', 0)
            },
            "improvement": improvement,
            "trend_direction": "Improving" if improvement['coverage_pct_change'] > 0 else "Declining" if improvement['coverage_pct_change'] < 0 else "Stable"
        }
    
    def _performance_summary(self, summary: Dict) -> Dict:
        """Generate performance summary"""
        covered = summary.get('total_covered', 0) or 0
        missing = summary.get('total_missing', 0) or 0
        total = covered + missing
        
        coverage_pct = (covered / total * 100) if total > 0 else 0
        
        return {
            "overall_coverage_percent": round(coverage_pct, 2),
            "total_executions": summary.get('total_executions', 0),
            "max_coverage_reached": round(summary.get('max_coverage', 0), 2),
            "min_coverage_reached": round(summary.get('min_coverage', 0), 2),
            "current_coverage": round(summary.get('current_coverage', 0), 2),
            "avg_execution_time_ms": round(summary.get('avg_duration_ms', 0), 2)
        }
    
    def _generate_insights(self, history: List[Dict], trends: List[Dict], 
                          summary: Dict) -> List[str]:
        """Generate actionable insights"""
        insights = []
        
        # Execution quality insight
        if history:
            success_rate = sum(1 for h in history if h['status'] == 'SUCCESS') / len(history) * 100
            if success_rate >= 95:
                insights.append("Excellent pipeline stability with 95%+ success rate")
            elif success_rate < 80:
                insights.append("Alert: Pipeline success rate below 80% - investigate failures")
        
        # Compliance trend insight
        if trends:
            sorted_trends = sorted(trends, key=lambda x: x['date'])
            latest = sorted_trends[-1].get('avg_coverage_percentage', 0)
            oldest = sorted_trends[0].get('avg_coverage_percentage', 0)
            
            if latest > oldest:
                improvement = latest - oldest
                insights.append(f"Positive trend: Compliance coverage improved by {improvement:.1f}% over period")
            elif latest < oldest:
                insights.append(f"Warning: Compliance coverage declined - review new RBI guidelines")
        
        # Gap analysis insight
        metrics = self._calculate_compliance_metrics(history)
        missing_pct = metrics.get('missing_percent', 0)
        if missing_pct > 50:
            insights.append(f"Critical: {missing_pct:.0f}% of guidelines have missing policy coverage - prioritize updates")
        elif missing_pct > 20:
            insights.append(f"Attention: {missing_pct:.0f}% of guidelines lack policy coverage - plan compliance updates")
        else:
            insights.append("Good: Strong policy coverage across most RBI guidelines")
        
        if not insights:
            insights.append("Baseline analysis - continue monitoring compliance trends")
        
        return insights
    
    def save_analytics(self, output_path: str = "reports/analytics.json") -> bool:
        """
        Save analytics report to JSON file
        
        Args:
            output_path: Path to save analytics JSON
        
        Returns:
            True if successful
        """
        try:
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(self.report, f, indent=2, default=str)
            
            logger.info(f"Analytics report saved to: {output_path}")
            return True
        
        except Exception as e:
            logger.error(f"Error saving analytics: {e}")
            return False
    
    def get_execution_timeline(self, limit: int = 10) -> List[Dict]:
        """Get execution timeline"""
        history = self.db.get_execution_history(limit=limit)
        return [
            {
                "execution_id": h['execution_id'],
                "timestamp": h['timestamp'],
                "duration_ms": h['total_duration_ms'],
                "status": h['status'],
                "gaps_identified": h['gaps_identified']
            }
            for h in history
        ]
    
    def close(self):
        """Close database connection"""
        self.db.close()


def main():
    """Test historical tracking"""
    tracker = HistoricalTracker()
    
    logger.info("Generating historical analytics...")
    report = tracker.generate_analytics_report(days=30)
    
    print("\n" + "="*80)
    print("HISTORICAL COMPLIANCE ANALYTICS")
    print("="*80)
    print(json.dumps(report, indent=2, default=str))
    print("="*80 + "\n")
    
    success = tracker.save_analytics()
    if success:
        print("[SUCCESS] Analytics saved to reports/analytics.json")
    
    tracker.close()


if __name__ == "__main__":
    main()
