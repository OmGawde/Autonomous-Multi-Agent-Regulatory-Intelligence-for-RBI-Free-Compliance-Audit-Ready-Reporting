import feedparser
import json
import logging
from datetime import datetime
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def fetch_rss_feed(feed_url):
    """
    Fetch and parse RBI RSS feed.
    
    Args:
        feed_url (str): URL of the RSS feed
        
    Returns:
        list: List of parsed feed entries with title, link, published_date, description
    """
    try:
        logger.info(f"Fetching RSS feed from: {feed_url}")
        feed = feedparser.parse(feed_url)
        
        # Check if feed was parsed successfully
        if feed.bozo:
            logger.warning(f"Feed parsing warning: {feed.bozo_exception}")
        
        entries = []
        for entry in feed.entries:
            parsed_entry = {
                'title': entry.get('title', ''),
                'link': entry.get('link', ''),
                'published_date': entry.get('published', ''),
                'description': entry.get('summary', '')
            }
            entries.append(parsed_entry)
        
        logger.info(f"Successfully parsed {len(entries)} entries from feed")
        return entries
    
    except Exception as e:
        logger.error(f"Error fetching RSS feed: {str(e)}")
        return []


def save_to_json(entries, output_path):
    """
    Save parsed entries to JSON file.
    
    Args:
        entries (list): List of parsed entries
        output_path (str): Path to save JSON file
    """
    try:
        # Create directory if it doesn't exist
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Prepare output data
        output_data = {
            'fetch_timestamp': datetime.now().isoformat(),
            'total_entries': len(entries),
            'entries': entries
        }
        
        # Write to JSON file
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Results saved to: {output_path}")
    
    except Exception as e:
        logger.error(f"Error saving to JSON: {str(e)}")


def main():
    """Main function to fetch RBI RSS feed and save results."""
    feed_url = "https://www.rbi.org.in/notifications_rss.xml"
    output_path = "data/rss/latest_entries.json"
    
    # Fetch feed
    entries = fetch_rss_feed(feed_url)
    
    # Save results
    if entries:
        save_to_json(entries, output_path)
        logger.info("RSS feed fetching completed successfully")
    else:
        logger.warning("No entries found or error occurred during fetch")


if __name__ == "__main__":
    main()
