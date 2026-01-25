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


def append_unique_entries(current_entries: List[Dict], new_entries: List[Dict]) -> tuple:
    """
    Append only new entries not already in current guidelines.
    Uses link field as unique identifier.
    
    Args:
        current_entries (list): Existing entries in guidelines
        new_entries (list): New entries to append
        
    Returns:
        tuple: (updated_entries_list, count_of_appended_entries)
    """
    current_links = extract_links_from_entries(current_entries)
    appended_count = 0
    
    for entry in new_entries:
        if 'link' in entry and entry['link']:
            if entry['link'] not in current_links:
                # Create entry preserving all fields including raw description
                new_entry = {
                    'title': entry.get('title', ''),
                    'link': entry.get('link', ''),
                    'published_date': entry.get('published_date', ''),
                    'description': entry.get('description', '')
                }
                current_entries.append(new_entry)
                appended_count += 1
                logger.info(f"Appended entry: {entry.get('title', 'Untitled')[:60]}...")
    
    return current_entries, appended_count


def initialize_guidelines(new_entries: List[Dict]) -> Dict:
    """
    Initialize new guidelines file with entries.
    
    Args:
        new_entries (list): New entries to initialize with
        
    Returns:
        dict: Initialized guidelines structure
    """
    return {
        'total_stored_entries': len(new_entries),
        'entries': new_entries
    }


def store_guidelines():
    """
    Main function to append new RBI guidelines to persistent store.
    
    Workflow:
    1. Load new_guidelines.json
    2. Load or create current_guidelines.json
    3. Extract entries from new_guidelines
    4. Append only unique entries (by link)
    5. Save updated current_guidelines.json
    """
    new_guidelines_path = "data/rss/new_guidelines.json"
    current_guidelines_path = "data/rbi_guidelines/current_guidelines.json"
    
    logger.info("Starting guidelines storage...")
    
    # Load new guidelines
    new_guidelines_data = load_json_file(new_guidelines_path)
    new_entries = new_guidelines_data.get('entries', [])
    
    logger.info(f"Loaded {len(new_entries)} new entries from new_guidelines.json")
    
    # Handle empty new_guidelines
    if not new_entries:
        logger.info("No new entries to store")
        return True
    
    # Load or create current guidelines
    current_guidelines_data = load_json_file(current_guidelines_path)
    
    if not current_guidelines_data:
        # File doesn't exist - initialize new guidelines file
        logger.info("Creating new current_guidelines.json")
        current_entries = []
    else:
        # File exists - get existing entries
        current_entries = current_guidelines_data.get('entries', [])
        logger.info(f"Loaded {len(current_entries)} existing entries from current_guidelines.json")
    
    # Append only unique entries
    updated_entries, appended_count = append_unique_entries(current_entries, new_entries)
    
    logger.info(f"Appended {appended_count} new unique entries")
    
    # Prepare updated guidelines structure
    updated_guidelines = {
        'total_stored_entries': len(updated_entries),
        'entries': updated_entries
    }
    
    # Save updated guidelines
    if save_json_file(updated_guidelines, current_guidelines_path):
        logger.info(f"Updated current_guidelines.json with {len(updated_entries)} total entries")
        return True
    else:
        logger.error("Failed to save updated guidelines")
        return False


def main():
    """Run guidelines storage."""
    success = store_guidelines()
    if success:
        logger.info("✓ Guidelines storage completed successfully")
    else:
        logger.error("✗ Guidelines storage encountered errors")


if __name__ == "__main__":
    main()
