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


def extract_links_from_entries(entries: List[Dict]) -> set:
    """
    Extract unique links from entries.
    
    Args:
        entries (list): List of entry dictionaries
        
    Returns:
        set: Set of unique links
    """
    links = set()
    for entry in entries:
        if 'link' in entry and entry['link']:
            links.add(entry['link'])
    return links


def find_new_entries(latest_entries: List[Dict], previous_entries: List[Dict]) -> List[Dict]:
    """
    Find new entries by comparing links.
    
    Args:
        latest_entries (list): Latest fetched entries
        previous_entries (list): Previously stored entries
        
    Returns:
        list: List of new entries (not in previous_entries)
    """
    previous_links = extract_links_from_entries(previous_entries)
    new_entries = []
    
    for entry in latest_entries:
        if 'link' in entry and entry['link'] not in previous_links:
            new_entries.append(entry)
    
    return new_entries


def detect_updates():
    """
    Main function to detect updates between latest and previous entries.
    
    Workflow:
    1. Load latest_entries.json
    2. Check if previous_entries.json exists
    3. If NOT exists (first run):
       - Copy latest to previous
       - Create empty new_guidelines.json
    4. If exists (subsequent runs):
       - Compare using links as unique identifier
       - Save new entries to new_guidelines.json
       - Update previous_entries.json
    """
    latest_path = "data/rss/latest_entries.json"
    previous_path = "data/rss/previous_entries.json"
    new_guidelines_path = "data/rss/new_guidelines.json"
    
    logger.info("Starting update detection...")
    
    # Load latest entries
    latest_data = load_json_file(latest_path)
    if not latest_data:
        logger.error("Failed to load latest_entries.json")
        return False
    
    latest_entries = latest_data.get('entries', [])
    logger.info(f"Loaded {len(latest_entries)} entries from latest_entries.json")
    
    # Check if previous entries exist
    previous_data = load_json_file(previous_path)
    previous_exists = bool(previous_data)
    
    if not previous_exists:
        # FIRST RUN: Copy latest to previous and create empty new_guidelines
        logger.info("First run detected. Initializing baseline...")
        
        # Save latest as previous
        if save_json_file(latest_data, previous_path):
            logger.info(f"Saved {len(latest_entries)} entries to previous_entries.json")
        
        # Create empty new_guidelines
        new_guidelines = {
            'fetch_timestamp': latest_data.get('fetch_timestamp', ''),
            'new_entries_count': 0,
            'entries': []
        }
        
        if save_json_file(new_guidelines, new_guidelines_path):
            logger.info("Created empty new_guidelines.json")
        
        logger.info("First run initialization complete")
        return True
    
    else:
        # SUBSEQUENT RUN: Compare and detect new entries
        logger.info("Subsequent run detected. Comparing entries...")
        
        previous_entries = previous_data.get('entries', [])
        new_entries = find_new_entries(latest_entries, previous_entries)
        
        logger.info(f"Found {len(new_entries)} new entries")
        
        # Save new entries to new_guidelines.json
        new_guidelines = {
            'fetch_timestamp': latest_data.get('fetch_timestamp', ''),
            'new_entries_count': len(new_entries),
            'entries': new_entries
        }
        
        if save_json_file(new_guidelines, new_guidelines_path):
            logger.info(f"Saved {len(new_entries)} new entries to new_guidelines.json")
        
        # Update previous_entries.json with latest
        if save_json_file(latest_data, previous_path):
            logger.info(f"Updated previous_entries.json with {len(latest_entries)} entries")
        
        logger.info("Update detection complete")
        return True


def main():
    """Run update detection."""
    success = detect_updates()
    if success:
        logger.info("✓ Update detection finished successfully")
    else:
        logger.error("✗ Update detection encountered errors")


if __name__ == "__main__":
    main()
