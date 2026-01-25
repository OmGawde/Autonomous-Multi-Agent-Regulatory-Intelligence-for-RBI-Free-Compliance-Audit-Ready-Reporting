import json
import logging
from pathlib import Path
from typing import List, Dict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_policy_file(file_path: str) -> str:
    """
    Load bank policy file content.
    
    Args:
        file_path (str): Path to policy file
        
    Returns:
        str: File content or empty string if file doesn't exist
    """
    try:
        if Path(file_path).exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            logger.warning(f"Policy file not found: {file_path}")
            return ""
    except Exception as e:
        logger.error(f"Error loading policy file: {str(e)}")
        return ""


def parse_policy_clauses(content: str) -> List[Dict]:
    """
    Parse policy content into clauses.
    
    Format: CLAUSE_ID: Clause text
    
    Args:
        content (str): Raw policy file content
        
    Returns:
        list: List of parsed clauses with clause_id and clause_text
    """
    clauses = []
    
    # Split by lines
    lines = content.split('\n')
    
    for line in lines:
        # Skip empty lines
        line = line.strip()
        if not line:
            continue
        
        # Parse ID: Text format
        if ':' in line:
            try:
                # Split on first colon only
                clause_id, clause_text = line.split(':', 1)
                clause_id = clause_id.strip()
                clause_text = clause_text.strip()
                
                # Only add if both ID and text are non-empty
                if clause_id and clause_text:
                    clauses.append({
                        'clause_id': clause_id,
                        'clause_text': clause_text
                    })
                    logger.info(f"Parsed clause: {clause_id}")
                else:
                    logger.warning(f"Skipping malformed clause: {line[:50]}...")
            except Exception as e:
                logger.warning(f"Error parsing line: {str(e)}")
                continue
        else:
            logger.warning(f"Skipping line without colon: {line[:50]}...")
    
    return clauses


def print_clauses(clauses: List[Dict]) -> None:
    """
    Print parsed clauses to console.
    
    Args:
        clauses (list): List of parsed clause dictionaries
    """
    if not clauses:
        logger.info("No clauses to display")
        return
    
    print("\n" + "="*80)
    print(f"TOTAL CLAUSES PARSED: {len(clauses)}")
    print("="*80 + "\n")
    
    for i, clause in enumerate(clauses, 1):
        clause_id = clause.get('clause_id', 'N/A').replace('\ufeff', '')  # Remove BOM
        clause_text = clause.get('clause_text', 'N/A')
        
        try:
            print(f"[{i}] Clause ID: {clause_id}")
            print(f"    Text: {clause_text}")
            print("-" * 80)
        except UnicodeEncodeError:
            # Handle encoding issues on Windows
            print(f"[{i}] Clause ID: {clause_id.encode('utf-8', errors='ignore').decode('utf-8')}")
            print(f"    Text: {clause_text.encode('utf-8', errors='ignore').decode('utf-8')}")
            print("-" * 80)
    
    print(f"\nTotal clauses: {len(clauses)}\n")


def save_policy_json(clauses: List[Dict], output_path: str) -> bool:
    """
    Save parsed clauses to JSON file.
    
    Args:
        clauses (list): List of parsed clause dictionaries
        output_path (str): Path to save JSON file
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Create directory if it doesn't exist
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Create JSON structure
        policy_json = {
            'total_clauses': len(clauses),
            'clauses': clauses
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(policy_json, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved policy JSON to: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Error saving policy JSON: {str(e)}")
        return False


def load_and_parse_policy():
    """
    Main function to load and parse bank policy.
    
    Workflow:
    1. Load policy from current_policy.txt
    2. Parse into clause_id and clause_text
    3. Ignore empty lines
    4. Save to current_policy.json
    5. Print parsed clauses
    """
    policy_txt_path = "data/bank_policies/current_policy.txt"
    policy_json_path = "data/bank_policies/current_policy.json"
    
    logger.info("Loading bank policy...")
    
    # Load policy file
    content = load_policy_file(policy_txt_path)
    
    if not content:
        logger.error("Failed to load policy file or file is empty")
        return False
    
    logger.info(f"Loaded policy file ({len(content)} bytes)")
    
    # Parse clauses
    clauses = parse_policy_clauses(content)
    
    if not clauses:
        logger.warning("No valid clauses found in policy file")
        return False
    
    logger.info(f"Parsed {len(clauses)} clauses")
    
    # Save to JSON
    if not save_policy_json(clauses, policy_json_path):
        logger.error("Failed to save policy JSON")
        return False
    
    # Print clauses
    print_clauses(clauses)
    
    return True


def main():
    """Run policy loader."""
    success = load_and_parse_policy()
    if success:
        logger.info("✓ Policy loading completed successfully")
    else:
        logger.error("✗ Policy loading encountered errors")


if __name__ == "__main__":
    main()
