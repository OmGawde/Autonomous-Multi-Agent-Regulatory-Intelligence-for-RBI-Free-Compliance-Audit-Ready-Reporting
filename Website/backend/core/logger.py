import logging
import sys
import os
import json
from datetime import datetime
from colorama import Fore, Style, init
from core.config import settings

# Initialize colorama
init(autoreset=True)

class ColoredFormatter(logging.Formatter):
    """Custom formatter for colored console output."""
    COLORS = {
        'DEBUG': Fore.BLUE,
        'INFO': Fore.GREEN,
        'WARNING': Fore.YELLOW,
        'ERROR': Fore.RED,
        'CRITICAL': Fore.MAGENTA + Style.BRIGHT,
    }

    def format(self, record):
        color = self.COLORS.get(record.levelname, '')
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
        log_msg = f"{timestamp} | {record.levelname:8} | {record.name:15} | {record.getMessage()}"
        return f"{color}{log_msg}{Style.RESET_ALL}"

def get_logger(name: str) -> logging.Logger:
    """Configures and returns a named logger with console and file handlers."""
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        # Console Handler
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(ColoredFormatter())
        logger.addHandler(stream_handler)

        # File Handler
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(os.path.join(log_dir, "pipeline.log"))
        file_formatter = logging.Formatter('%(asctime)s | %(levelname)8s | %(name)15s | %(message)s')
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        # Set Log Level
        log_level_str = getattr(settings, 'LOG_LEVEL', 'DEBUG')
        log_level = getattr(logging, log_level_str.upper(), logging.DEBUG)
        logger.setLevel(log_level)
        
        logger.propagate = False

    return logger

def log_state(logger: logging.Logger, stage: str, state: dict) -> None:
    """Logs the complete state of the pipeline at a specific stage with formatting."""
    logger.info(f"===== STAGE: {stage} =====")
    for key, value in state.items():
        if isinstance(value, (dict, list)):
            try:
                formatted_value = json.dumps(value, indent=2, default=str)
                if isinstance(value, list):
                    logger.info(f"{key} (Count={len(value)}):\n{formatted_value}")
                else:
                    logger.info(f"{key}:\n{formatted_value}")
            except Exception as e:
                logger.info(f"{key}: {value} (Error formatting: {e})")
        elif isinstance(value, str) and len(value) > 200:
            logger.info(f"{key}: {value[:200]}... (truncated)")
        else:
            logger.info(f"{key}: {value}")
    logger.info(f"===== END: {stage} =====")

def log_pipeline_transition(logger: logging.Logger, from_node: str, to_node: str, state: dict) -> None:
    """Logs a clear transition between pipeline nodes with key status info."""
    logger.info(f"--> Transitioning from {from_node} to {to_node}")
    
    if 'extraction_status' in state:
        logger.info(f"Extraction Status: {state['extraction_status']}")
    if 'error_message' in state and state['error_message']:
        logger.warning(f"Error Message: {state['error_message']}")
    if 'transactions' in state and state['transactions']:
        logger.info(f"Transaction Count: {len(state['transactions'])}")
    if 'loan_result' in state and state['loan_result']:
        decision = state['loan_result'].get('decision')
        if decision:
            logger.info(f"Current Decision: {decision.upper()}")
