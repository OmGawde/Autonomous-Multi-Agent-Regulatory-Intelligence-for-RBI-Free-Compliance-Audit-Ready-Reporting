#!/usr/bin/env python3
"""
RBI Compliance Monitoring Pipeline Orchestrator

Executes all 6 steps of the compliance monitoring pipeline in sequence:
1. RSS Feed Ingestion (fetch_rss.py)
2. Change Detection (detect_updates.py)
3. Persistent Storage (store_guidelines.py)
4. Bank Policy Normalization (load_bank_policy.py)
5. Compliance Gap Analysis (detect_gaps.py)
6. Audit-Ready Report Generation (generate_report.py)
"""

import sys
import time
import logging
from datetime import datetime
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_header(title: str) -> None:
    """Print formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def print_footer(title: str, duration_ms: float, success: bool) -> None:
    """Print formatted section footer."""
    status = "✓ SUCCESS" if success else "✗ FAILED"
    print(f"\n{status} - {title} completed in {duration_ms:.0f}ms\n")


def run_step_1_fetch_rss() -> tuple[bool, float]:
    """Step 1: RSS Feed Ingestion"""
    print_header("STEP 1: RSS FEED INGESTION")
    start = time.time()
    
    try:
        logger.info("[STEP 1] Initializing RSS feed ingestion module...")
        
        # Import and run
        from src.rss_scanner.fetch_rss import main as fetch_rss_main
        logger.info("[STEP 1] Module imported successfully")
        
        logger.info("[STEP 1] Fetching RBI RSS feed from: https://www.rbi.org.in/notifications_rss.xml")
        fetch_rss_main()
        logger.info("[STEP 1] RSS feed fetched and parsed successfully")
        
        # Verify output
        if Path("data/rss/latest_entries.json").exists():
            logger.info("[STEP 1] Output file verified: data/rss/latest_entries.json")
        else:
            logger.warning("[STEP 1] Output file not found: data/rss/latest_entries.json")
        
        duration = (time.time() - start) * 1000
        print_footer("RSS Feed Ingestion", duration, True)
        return True, duration
    
    except Exception as e:
        duration = (time.time() - start) * 1000
        logger.error(f"[STEP 1] RSS Feed Ingestion failed: {str(e)}", exc_info=True)
        print_footer("RSS Feed Ingestion", duration, False)
        return False, duration


def run_step_2_detect_updates() -> tuple[bool, float]:
    """Step 2: Change Detection"""
    print_header("STEP 2: CHANGE DETECTION")
    start = time.time()
    
    try:
        logger.info("[STEP 2] Initializing change detection module...")
        
        # Import and run
        from src.rss_scanner.detect_updates import main as detect_updates_main
        logger.info("[STEP 2] Module imported successfully")
        
        logger.info("[STEP 2] Loading data/rss/latest_entries.json")
        logger.info("[STEP 2] Comparing with previous_entries.json (if exists)")
        detect_updates_main()
        logger.info("[STEP 2] Change detection completed")
        
        # Verify outputs
        new_guidelines_exists = Path("data/rss/new_guidelines.json").exists()
        previous_entries_exists = Path("data/rss/previous_entries.json").exists()
        logger.info(f"[STEP 2] Output files - new_guidelines: {new_guidelines_exists}, previous_entries: {previous_entries_exists}")
        
        duration = (time.time() - start) * 1000
        print_footer("Change Detection", duration, True)
        return True, duration
    
    except Exception as e:
        duration = (time.time() - start) * 1000
        logger.error(f"[STEP 2] Change Detection failed: {str(e)}", exc_info=True)
        print_footer("Change Detection", duration, False)
        return False, duration


def run_step_3_store_guidelines() -> tuple[bool, float]:
    """Step 3: Persistent Storage"""
    print_header("STEP 3: PERSISTENT STORAGE")
    start = time.time()
    
    try:
        logger.info("[STEP 3] Initializing guidelines storage module...")
        
        # Import and run
        from src.rss_scanner.store_guidelines import main as store_guidelines_main
        logger.info("[STEP 3] Module imported successfully")
        
        logger.info("[STEP 3] Loading data/rss/new_guidelines.json")
        logger.info("[STEP 3] Loading or creating data/rbi_guidelines/current_guidelines.json")
        store_guidelines_main()
        logger.info("[STEP 3] Appending unique entries to persistent store")
        
        # Verify output
        if Path("data/rbi_guidelines/current_guidelines.json").exists():
            logger.info("[STEP 3] Output file verified: data/rbi_guidelines/current_guidelines.json")
        else:
            logger.warning("[STEP 3] Output file not found: data/rbi_guidelines/current_guidelines.json")
        
        duration = (time.time() - start) * 1000
        print_footer("Persistent Storage", duration, True)
        return True, duration
    
    except Exception as e:
        duration = (time.time() - start) * 1000
        logger.error(f"[STEP 3] Persistent Storage failed: {str(e)}", exc_info=True)
        print_footer("Persistent Storage", duration, False)
        return False, duration


def run_step_4_load_bank_policy() -> tuple[bool, float]:
    """Step 4: Bank Policy Normalization"""
    print_header("STEP 4: BANK POLICY NORMALIZATION")
    start = time.time()
    
    try:
        logger.info("[STEP 4] Initializing bank policy loader module...")
        
        # Check if input file exists
        if not Path("data/bank_policies/current_policy.txt").exists():
            logger.warning("[STEP 4] Input file not found: data/bank_policies/current_policy.txt")
            logger.warning("[STEP 4] Please create a policy file in ID: Text format")
            raise FileNotFoundError("current_policy.txt not found")
        logger.info("[STEP 4] Input file found: data/bank_policies/current_policy.txt")
        
        # Import and run
        from src.comparator.load_bank_policy import main as load_bank_policy_main
        logger.info("[STEP 4] Module imported successfully")
        
        logger.info("[STEP 4] Parsing policy file (ID: Text format)")
        load_bank_policy_main()
        logger.info("[STEP 4] Saving parsed clauses to JSON")
        
        # Verify output
        if Path("data/bank_policies/current_policy.json").exists():
            logger.info("[STEP 4] Output file verified: data/bank_policies/current_policy.json")
        else:
            logger.warning("[STEP 4] Output file not found: data/bank_policies/current_policy.json")
        
        duration = (time.time() - start) * 1000
        print_footer("Bank Policy Normalization", duration, True)
        return True, duration
    
    except Exception as e:
        duration = (time.time() - start) * 1000
        logger.error(f"[STEP 4] Bank Policy Normalization failed: {str(e)}", exc_info=True)
        print_footer("Bank Policy Normalization", duration, False)
        return False, duration


def run_step_5_detect_gaps() -> tuple[bool, float]:
    """Step 5: Compliance Gap Analysis"""
    print_header("STEP 5: COMPLIANCE GAP ANALYSIS")
    start = time.time()
    
    try:
        logger.info("[STEP 5] Initializing gap detection module...")
        
        # Verify input files
        guidelines_exists = Path("data/rbi_guidelines/current_guidelines.json").exists()
        policy_exists = Path("data/bank_policies/current_policy.json").exists()
        logger.info(f"[STEP 5] Input files - guidelines: {guidelines_exists}, policy: {policy_exists}")
        
        if not guidelines_exists or not policy_exists:
            logger.error("[STEP 5] Required input files missing")
            raise FileNotFoundError("Input files not found")
        
        # Import and run
        from src.comparator.detect_gaps import main as detect_gaps_main
        logger.info("[STEP 5] Module imported successfully")
        
        logger.info("[STEP 5] Comparing RBI guidelines against bank policy")
        logger.info("[STEP 5] Using keyword-based matching logic")
        detect_gaps_main()
        logger.info("[STEP 5] Gap classification completed")
        
        # Verify output
        if Path("data/output/gap_analysis.json").exists():
            logger.info("[STEP 5] Output file verified: data/output/gap_analysis.json")
        else:
            logger.warning("[STEP 5] Output file not found: data/output/gap_analysis.json")
        
        duration = (time.time() - start) * 1000
        print_footer("Compliance Gap Analysis", duration, True)
        return True, duration
    
    except Exception as e:
        duration = (time.time() - start) * 1000
        logger.error(f"[STEP 5] Compliance Gap Analysis failed: {str(e)}", exc_info=True)
        print_footer("Compliance Gap Analysis", duration, False)
        return False, duration


def run_step_6_generate_report() -> tuple[bool, float]:
    """Step 6: Audit-Ready Report Generation"""
    print_header("STEP 6: AUDIT-READY REPORT GENERATION")
    start = time.time()
    
    try:
        logger.info("[STEP 6] Initializing report generation module...")
        
        # Verify input files
        gap_analysis_exists = Path("data/output/gap_analysis.json").exists()
        logger.info(f"[STEP 6] Input file - gap_analysis: {gap_analysis_exists}")
        
        if not gap_analysis_exists:
            logger.warning("[STEP 6] Note: gap_analysis.json not found, report may use mock data")
        
        # Import and run
        from src.exporter.generate_report import main as generate_report_main
        logger.info("[STEP 6] Module imported successfully")
        
        logger.info("[STEP 6] Loading gap analysis and RBI guidelines")
        logger.info("[STEP 6] Merging data using rule_id")
        logger.info("[STEP 6] Computing overall compliance status")
        logger.info("[STEP 6] Generating 10-section structured report")
        generate_report_main()
        logger.info("[STEP 6] Report generation completed")
        
        # Verify output
        if Path("reports/compliance_report.json").exists():
            logger.info("[STEP 6] Output file verified: reports/compliance_report.json")
        else:
            logger.warning("[STEP 6] Output file not found: reports/compliance_report.json")
        
        duration = (time.time() - start) * 1000
        print_footer("Audit-Ready Report Generation", duration, True)
        return True, duration
    
    except Exception as e:
        duration = (time.time() - start) * 1000
        logger.error(f"[STEP 6] Audit-Ready Report Generation failed: {str(e)}", exc_info=True)
        print_footer("Audit-Ready Report Generation", duration, False)
        return False, duration


def run_complete_pipeline() -> bool:
    """
    Execute all 6 steps of the compliance monitoring pipeline.
    
    Returns:
        bool: True if all steps succeeded, False otherwise
    """
    pipeline_start = time.time()
    
    print_header("RBI COMPLIANCE MONITORING PIPELINE (PoC)")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    logger.info("=" * 80)
    logger.info("PIPELINE INITIALIZATION")
    logger.info(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Execution mode: Sequential with fail-fast")
    logger.info("=" * 80)
    
    # Track results
    results = []
    timings = {}
    
    # Step 1: RSS Feed Ingestion
    logger.info("\n[PIPELINE] Starting Step 1: RSS Feed Ingestion")
    success, duration = run_step_1_fetch_rss()
    results.append(('RSS Feed Ingestion', success))
    timings['rss_fetch'] = duration
    if not success:
        logger.error("[PIPELINE] Pipeline halted at Step 1 - see errors above")
        return False
    logger.info(f"[PIPELINE] Step 1 completed successfully in {duration:.0f}ms")
    
    # Step 2: Change Detection
    logger.info("\n[PIPELINE] Starting Step 2: Change Detection")
    success, duration = run_step_2_detect_updates()
    results.append(('Change Detection', success))
    timings['change_detection'] = duration
    if not success:
        logger.error("[PIPELINE] Pipeline halted at Step 2 - see errors above")
        return False
    logger.info(f"[PIPELINE] Step 2 completed successfully in {duration:.0f}ms")
    
    # Step 3: Persistent Storage
    logger.info("\n[PIPELINE] Starting Step 3: Persistent Storage")
    success, duration = run_step_3_store_guidelines()
    results.append(('Persistent Storage', success))
    timings['persistent_storage'] = duration
    if not success:
        logger.error("[PIPELINE] Pipeline halted at Step 3 - see errors above")
        return False
    logger.info(f"[PIPELINE] Step 3 completed successfully in {duration:.0f}ms")
    
    # Step 4: Bank Policy Normalization
    logger.info("\n[PIPELINE] Starting Step 4: Bank Policy Normalization")
    success, duration = run_step_4_load_bank_policy()
    results.append(('Bank Policy Normalization', success))
    timings['policy_normalization'] = duration
    if not success:
        logger.error("[PIPELINE] Pipeline halted at Step 4 - see errors above")
        return False
    logger.info(f"[PIPELINE] Step 4 completed successfully in {duration:.0f}ms")
    
    # Step 5: Compliance Gap Analysis
    logger.info("\n[PIPELINE] Starting Step 5: Compliance Gap Analysis")
    success, duration = run_step_5_detect_gaps()
    results.append(('Compliance Gap Analysis', success))
    timings['gap_analysis'] = duration
    if not success:
        logger.error("[PIPELINE] Pipeline halted at Step 5 - see errors above")
        return False
    logger.info(f"[PIPELINE] Step 5 completed successfully in {duration:.0f}ms")
    
    # Step 6: Audit-Ready Report Generation
    logger.info("\n[PIPELINE] Starting Step 6: Audit-Ready Report Generation")
    success, duration = run_step_6_generate_report()
    results.append(('Audit-Ready Report Generation', success))
    timings['report_generation'] = duration
    if not success:
        logger.error("[PIPELINE] Pipeline halted at Step 6 - see errors above")
        return False
    logger.info(f"[PIPELINE] Step 6 completed successfully in {duration:.0f}ms")
    
    # Calculate total time
    total_duration = (time.time() - pipeline_start) * 1000
    
    # Print final summary
    print_header("PIPELINE EXECUTION SUMMARY")
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    logger.info("\n[PIPELINE] All steps completed successfully!")
    logger.info(f"[PIPELINE] Total execution time: {total_duration:.0f}ms ({total_duration/1000:.2f}s)")
    
    print("Step Results:")
    for i, (step, success) in enumerate(results, 1):
        status = "✓ PASS" if success else "✗ FAIL"
        duration = timings.get(list(timings.keys())[i-1], 0)
        print(f"  [{i}] {step:.<50} {status} ({duration:.0f}ms)")
        logger.info(f"[SUMMARY] Step {i} ({step}): {status} - {duration:.0f}ms")
    
    print(f"\nTotal Execution Time: {total_duration:.0f}ms ({total_duration/1000:.2f}s)")
    
    print("\nOutput Files Generated:")
    output_files = [
        ("data/rss/latest_entries.json", "Raw RBI RSS feed entries"),
        ("data/rss/new_guidelines.json", "Newly detected entries"),
        ("data/rss/previous_entries.json", "Baseline for next run"),
        ("data/rbi_guidelines/current_guidelines.json", "Persistent guidelines store"),
        ("data/bank_policies/current_policy.json", "Normalized bank policy"),
        ("data/output/gap_analysis.json", "Compliance gap analysis"),
        ("reports/compliance_report.json", "Final audit-ready report")
    ]
    
    for file_path, description in output_files:
        exists = Path(file_path).exists()
        status = "✓" if exists else "✗"
        print(f"  {status} {file_path:.<50} {description}")
        logger.info(f"[FILES] {file_path}: {'EXISTS' if exists else 'MISSING'}")
    
    print("\n" + "=" * 80)
    print("  ✓ PIPELINE EXECUTION COMPLETED SUCCESSFULLY")
    print("=" * 80 + "\n")
    
    logger.info("=" * 80)
    logger.info("PIPELINE EXECUTION COMPLETED")
    logger.info(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Total duration: {total_duration:.0f}ms")
    logger.info("=" * 80)
    
    return True


def main():
    """Main entry point."""
    try:
        logger.info("RBI Compliance Monitoring Pipeline - Starting")
        success = run_complete_pipeline()
        
        if success:
            logger.info("Pipeline execution: SUCCESS")
            sys.exit(0)
        else:
            logger.error("Pipeline execution: FAILED - Check logs above for details")
            sys.exit(1)
    
    except KeyboardInterrupt:
        logger.warning("Pipeline interrupted by user (Ctrl+C)")
        print("\n[INTERRUPTED] Pipeline stopped by user")
        sys.exit(130)
    
    except Exception as e:
        logger.error(f"Unexpected error in pipeline: {str(e)}", exc_info=True)
        print(f"\n[ERROR] Unexpected error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
