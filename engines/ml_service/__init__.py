"""
engines/ml_service/__init__.py
Unified entry point for ML analysis.
Delegates to smart_ingestion via the processor bridge.
"""
import logging
from smart_ingestion.config import settings

def analyze_content(data: dict):
    """
    Unified entry point for ML analysis.
    
    Args:
        data (dict): A dictionary containing:
            - type (str): The type of analysis.
            - content (str): The content to analyze.
            - extra_args (dict, optional): Additional arguments.
            
    Returns:
        The result of the analysis from the smart_ingestion pipeline.
    """
    try:
        from .processor import analyze_content as real_analyze
        return real_analyze(data)
    except Exception as e:
        logging.error(f"Error during ML processing: {e}")
        raise e
