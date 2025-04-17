"""
Backup manager utility module.

Provides functionality for creating timestamped backups of configuration files
and managing backup rotation to prevent excessive disk usage while maintaining
a history of application settings.
"""

import os
import json
import time
import shutil
from datetime import datetime
import logging

def backup_streamers_config(config_dir, max_backups=5):
    """
    Create a timestamped backup of the streamers configuration file.
    
    Creates a backup of the streamers.json file in a dedicated backup directory.
    Maintains only the specified number of most recent backups to prevent
    excessive disk usage.
    
    Args:
        config_dir (str): Directory containing the configuration files
        max_backups (int, optional): Maximum number of backup files to keep. Defaults to 5.
        
    Returns:
        bool: True if backup was successful, False otherwise
    """
    streamers_file = os.path.join(config_dir, "streamers.json")
    
    # Skip backup if source file doesn't exist
    if not os.path.exists(streamers_file):
        print("[Backup] No streamers.json file found to backup")
        return False
    
    # Ensure backup directory exists
    backup_dir = os.path.join(config_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    
    # Create timestamped filename for the backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"streamers_{timestamp}.json"
    backup_path = os.path.join(backup_dir, backup_filename)
    
    try:
        # Create backup by copying the current configuration file
        shutil.copy2(streamers_file, backup_path)
        
        # Find all existing backup files
        backups = [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) 
                  if f.startswith("streamers_") and f.endswith(".json")]
        
        # Sort backups by modification time (newest first)
        backups.sort(key=os.path.getmtime, reverse=True)
        
        # Remove older backups to maintain the specified limit
        if len(backups) > max_backups:
            for old_backup in backups[max_backups:]:
                os.remove(old_backup)

        return True
    except Exception as e:
        print(f"[Backup] Error creating backup: {e}")
        return False