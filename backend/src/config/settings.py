"""
Application settings management module.
Handles configuration file paths, storage locations, and streamer management.
"""

import os
import json
import platform
from typing import Dict, Any, Set

# Define config directory based on platform
if platform.system() == "Windows":
    # Windows: Use AppData\Roaming
    CONFIG_DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), "NazareinsTwitchDownloader")
else:
    # Linux: Use ~/.config/NazareinsTwitchDownloader/
    CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.config', "NazareinsTwitchDownloader")

# Create the directory if it doesn't exist
os.makedirs(CONFIG_DIR, exist_ok=True)

# Define the paths to save settings data
STREAMERS_FILE = os.path.join(CONFIG_DIR, "streamers.json")
STORAGE_CONFIG_FILE = os.path.join(CONFIG_DIR, "storage_config.json")

def get_default_storage_path() -> str:
    """
    Determine the default storage path based on the operating system.
    
    Returns:
        str: Path to the default download directory for stream recordings
             (~/Downloads/Streams on both Windows and Linux)
    """
    if platform.system() == "Windows":
        return os.path.join(os.path.expanduser("~"), "Downloads", "Streams")
    else:
        return os.path.join(os.path.expanduser("~"), "Downloads", "Streams")
    
def get_storage_path() -> str:
    """
    Retrieve the configured global storage path for downloads.
    
    Reads from the storage configuration file if it exists,
    otherwise falls back to the default path.
    
    Returns:
        str: Path where stream recordings will be saved
    """
    try:
        if os.path.exists(STORAGE_CONFIG_FILE):
            with open(STORAGE_CONFIG_FILE, "r") as f:
                return json.load(f).get("path", get_default_storage_path())
    except Exception as e:
        print(f"Error reading storage config: {e}")
    
    # Default path
    return get_default_storage_path()

def update_storage_path(new_path: str) -> bool:
    """
    Update the global storage path configuration.
    
    Args:
        new_path (str): New directory path for storing stream recordings
        
    Returns:
        bool: True if the update was successful, False otherwise
        
    Note:
        Creates the directory if it doesn't exist
    """
    try:
        os.makedirs(os.path.dirname(STORAGE_CONFIG_FILE), exist_ok=True)
        
        # Ensure the new path exists
        os.makedirs(new_path, exist_ok=True)
        
        with open(STORAGE_CONFIG_FILE, "w") as f:
            json.dump({"path": new_path}, f, indent=2)
        return True
    except Exception as e:
        print(f"Error updating storage path: {e}")
        return False

def get_monitored_streamers() -> Dict:
    """
    Retrieve the list of streamers being monitored.
    
    Reads the streamers configuration file and ensures all entries
    have the required fields with appropriate default values.
    
    Returns:
        Dict: Dictionary mapping streamer usernames to their configuration settings
              Returns an empty dictionary if the file doesn't exist or there's an error
    """
    try:
        if os.path.exists(STREAMERS_FILE):
            with open(STREAMERS_FILE, "r") as f:
                streamers = json.load(f)
                # If it's a list (older format), convert to dict
                if isinstance(streamers, list):
                    return {streamer: {
                        "downloads_enabled": False,
                        "twitch_id": "",
                        "save_directory": get_default_storage_path()
                    } for streamer in streamers}
                
                # Ensure all streamers have the required fields
                for streamer, settings in streamers.items():
                    if "downloads_enabled" not in settings:
                        settings["downloads_enabled"] = False
                    if "twitch_id" not in settings:
                        settings["twitch_id"] = ""
                    if "save_directory" not in settings:
                        settings["save_directory"] = get_default_storage_path()
                
                return streamers
    except Exception as e:
        print(f"Error reading streamers file: {e}")
    
    # Return empty dict if file doesn't exist or there's an error
    return {}

def update_monitored_streamers(streamers: Dict) -> None:
    """
    Update the monitored streamers configuration file.
    
    Args:
        streamers (Dict): Dictionary mapping streamer usernames to their settings
        
    Note:
        Uses a temporary file for writing to prevent data corruption if
        the operation is interrupted. Normalizes all streamer entries to
        ensure they have required fields with appropriate default values.
    """
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(STREAMERS_FILE), exist_ok=True)
        
        # Get existing streamers to detect new additions and changes
        existing_streamers = {}
        if os.path.exists(STREAMERS_FILE):
            try:
                with open(STREAMERS_FILE, "r") as f:
                    existing_streamers = json.load(f)
            except:
                pass
        
        # Create a cleaned copy with all necessary fields
        cleaned_streamers = {}
        for streamer, settings in streamers.items():
            cleaned_streamers[streamer] = {
                # Persistent configuration
                "downloads_enabled": settings.get("downloads_enabled", False),
                "twitch_id": settings.get("twitch_id", ""),
                "save_directory": settings.get("save_directory", get_default_storage_path()),
                "stream_resolution": settings.get("stream_resolution", "best"),
                
                # Profile and images
                "profileImageURL": settings.get("profileImageURL", ""),
                "offlineImageURL": settings.get("offlineImageURL", ""),
                
                # Status information - preserve these values now
                "isLive": settings.get("isLive", False),
                "title": settings.get("title", f"{streamer}'s Stream"),
                "thumbnail": settings.get("thumbnail", ""),
            }
        
        # Write to a temporary file first, then rename to avoid corruption
        temp_file = f"{STREAMERS_FILE}.tmp"
        with open(temp_file, "w") as f:
            json.dump(cleaned_streamers, f, indent=2)
        
        # Replace the original file with the temporary file
        os.replace(temp_file, STREAMERS_FILE)
        
    except Exception as e:
        print(f"Error saving streamers file: {e}")

def get_streamer_storage_path(streamer: str) -> str:
    """
    Get the configured storage path for a specific streamer.
    
    Args:
        streamer (str): Twitch username of the streamer
        
    Returns:
        str: Path where recordings for this specific streamer will be saved.
             If no custom path is configured, returns a subdirectory of the
             global path with the streamer's username.
    """
    streamers = get_monitored_streamers()
    if streamer in streamers and "save_directory" in streamers[streamer]:
        return streamers[streamer]["save_directory"]
    return os.path.join(get_storage_path(), streamer)

def update_streamer_storage_path(streamer: str, path: str) -> bool:
    """
    Update the storage path for a specific streamer.
    
    Args:
        streamer (str): Twitch username of the streamer
        path (str): New directory path for storing this streamer's recordings
        
    Returns:
        bool: True if the update was successful, False otherwise
        
    Note:
        Creates a new streamer entry if it doesn't exist.
        Ensures the specified directory exists.
    """
    try:
        streamers = get_monitored_streamers()
        
        # Create streamer entry if it doesn't exist
        if streamer not in streamers:
            streamers[streamer] = {
                "downloads_enabled": False,
                "twitch_id": "",
                "save_directory": path
            }
        else:
            # Update storage path
            streamers[streamer]["save_directory"] = path
        
        # Ensure the directory exists
        os.makedirs(path, exist_ok=True)
        
        # Save changes
        update_monitored_streamers(streamers)
        return True
    except Exception as e:
        print(f"Error updating streamer storage path: {e}")
        return False