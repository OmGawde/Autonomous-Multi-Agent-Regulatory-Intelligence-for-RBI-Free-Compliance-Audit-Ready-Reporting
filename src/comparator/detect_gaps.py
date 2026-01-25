import json
import logging
import re
from pathlib import Path
from typing import List, Dict
from html.parser import HTMLParser

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HTMLTextExtractor(HTMLParser):
    """Extract plain text from HTML content."""
    
    def __init__(self):
        super().__init__()
        self.text = []
    
    def handle_data(self, data):
        self.text.append(data)
    
    def get_text(self):
        return ' '.join(self.text)


def load_json_file(file_path: str) -> Dict:
    """
    Load JSON file safely.
    
    Args:
        file_path (str): Path to JSON file
        
    Returns:
        dict: Parsed JSON content or empty dict if file doesn't exist
    """
    try:
        if Path(file_path).exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            logger.warning(f"File not found: {file_path}")
            return {}
    except Exception as e:
        logger.error(f"Error loading {file_path}: {str(e)}")
        return {}


def save_json_file(data: Dict, file_path: str) -> bool:
    """
    Save data to JSON file.
    
    Args:
        data (dict): Data to save
        file_path (str): Path to save JSON file
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Create directory if it doesn't exist
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved to: {file_path}")
        return True
    except Exception as e:
        logger.error(f"Error saving to {file_path}: {str(e)}")
        return False


def extract_text_from_html(html_content: str) -> str:
    """
    Extract plain text from HTML content.
    
    Args:
        html_content (str): HTML content string
        
    Returns:
        str: Plain text extracted from HTML
    """
    try:
        parser = HTMLTextExtractor()
        parser.feed(html_content)
        return parser.get_text()
    except Exception as e:
        logger.warning(f"Error extracting text from HTML: {str(e)}")
        return html_content


def extract_keywords(text: str) -> set:
    """
    Extract keywords from text using simple tokenization.
    Extracts words (3+ characters) in lowercase.
    
    Args:
        text (str): Text to extract keywords from
        
    Returns:
        set: Set of extracted keywords
    """
    # Remove HTML tags if any
    text = re.sub(r'<[^>]+>', '', text)
    
    # Remove special characters and convert to lowercase
    text = re.sub(r'[^a-zA-Z0-9\s]', ' ', text)
    text = text.lower()
    
    # Extract words (3+ characters)
    words = set()
    for word in text.split():
        if len(word) >= 3:
            words.add(word)
    
    return words


def classify_compliance(guideline_text: str, policy_clauses: List[Dict]) -> str:
    """
    Classify compliance status based on keyword matching.
    
    Logic:
    - COVERED: Guideline keywords found in policy clauses
    - MISSING: No guideline keywords found in any policy clause
    - OUTDATED: Partial match (some keywords found but not all key terms)
    
    Args:
        guideline_text (str): RBI guideline text (title + description)
        policy_clauses (list): List of bank policy clauses
        
    Returns:
        str: Status classification (COVERED, MISSING, OUTDATED)
    """
    # Extract keywords from guideline
    guideline_keywords = extract_keywords(guideline_text)
    
    if not guideline_keywords:
        return "MISSING"
    
    # Track matches across all clauses
    total_matches = 0
    
    for clause in policy_clauses:
        clause_text = clause.get('clause_text', '')
        clause_keywords = extract_keywords(clause_text)
        
        # Count how many guideline keywords appear in this clause
        matches = len(guideline_keywords & clause_keywords)
        total_matches += matches
    
    # Classification logic
    matched_percentage = (total_matches / len(guideline_keywords)) * 100 if guideline_keywords else 0
    
    if matched_percentage >= 80:
        return "COVERED"
    elif matched_percentage >= 30:
        return "OUTDATED"
    else:
        return "MISSING"


def detect_compliance_gaps():
    """
    Main function to detect compliance gaps.
    
    Workflow:
    1. Load RBI guidelines from current_guidelines.json
    2. Load bank policy from current_policy.json
    3. For each RBI guideline:
       - Extract keywords from title and description
       - Check if keywords appear in policy clauses
       - Classify as MISSING, OUTDATED, or COVERED
    4. Save results to gap_analysis.json
    """
    guidelines_path = "data/rbi_guidelines/current_guidelines.json"
    policy_path = "data/bank_policies/current_policy.json"
    gaps_path = "data/output/gap_analysis.json"
    
    logger.info("Starting compliance gap detection...")
    
    # Load guidelines
    guidelines_data = load_json_file(guidelines_path)
    guidelines_entries = guidelines_data.get('entries', [])
    
    if not guidelines_entries:
        logger.error("No RBI guidelines found")
        return False
    
    logger.info(f"Loaded {len(guidelines_entries)} RBI guidelines")
    
    # Load policy
    policy_data = load_json_file(policy_path)
    policy_clauses = policy_data.get('clauses', [])
    
    if not policy_clauses:
        logger.error("No bank policy clauses found")
        return False
    
    logger.info(f"Loaded {len(policy_clauses)} bank policy clauses")
    
    # Analyze each guideline
    gaps = []
    status_counts = {'COVERED': 0, 'OUTDATED': 0, 'MISSING': 0}
    
    for idx, guideline in enumerate(guidelines_entries, 1):
        guideline_title = guideline.get('title', '')
        guideline_description = guideline.get('description', '')
        guideline_link = guideline.get('link', '')
        
        # Combine title and description for analysis
        full_text = f"{guideline_title} {guideline_description}"
        
        # Extract plain text from HTML description
        full_text = extract_text_from_html(full_text)
        
        # Classify compliance
        status = classify_compliance(full_text, policy_clauses)
        status_counts[status] += 1
        
        gap = {
            'guideline_id': idx,
            'guideline_title': guideline_title,
            'guideline_link': guideline_link,
            'compliance_status': status,
            'keyword_count': len(extract_keywords(full_text))
        }
        
        gaps.append(gap)
        
        logger.info(f"Guideline {idx}: {status} - {guideline_title[:60]}...")
    
    # Prepare output
    output = {
        'total_guidelines_analyzed': len(guidelines_entries),
        'total_policy_clauses': len(policy_clauses),
        'status_summary': {
            'covered': status_counts['COVERED'],
            'outdated': status_counts['OUTDATED'],
            'missing': status_counts['MISSING']
        },
        'gaps': gaps
    }
    
    # Save results
    if save_json_file(output, gaps_path):
        logger.info(f"Saved compliance gaps analysis")
        logger.info(f"  COVERED: {status_counts['COVERED']}")
        logger.info(f"  OUTDATED: {status_counts['OUTDATED']}")
        logger.info(f"  MISSING: {status_counts['MISSING']}")
        return True
    else:
        logger.error("Failed to save compliance gaps")
        return False


def main():
    """Run gap detection."""
    success = detect_compliance_gaps()
    if success:
        logger.info("✓ Compliance gap detection completed successfully")
    else:
        logger.error("✗ Compliance gap detection encountered errors")


if __name__ == "__main__":
    main()
