"""
Windows System Tray Integration Module

This module provides system tray integration for the Twitch Downloader application
on Windows platforms. It creates a system tray icon with menu options to:
- Open the web UI in the default browser
- Toggle automatic startup on Windows boot
- Exit the application

The module handles:
- System-specific imports (Windows only)
- Icon loading with fallback mechanisms
- Windows startup registration via shortcuts or registry
- Menu creation and event handling

Usage:
    # Initialize and start the system tray service
    tray_service = SystemTrayService(web_port=8420)
    tray_service.start()
    
    # Later, to stop the service
    tray_service.stop()
"""

import os
import sys
import platform
import webbrowser
import threading
import subprocess
from pathlib import Path

# Only import Windows-specific libraries when on Windows
if platform.system() == "Windows":
    import pystray
    from PIL import Image, ImageDraw
    import winreg

class SystemTrayService:
    """
    Windows system tray integration service for Twitch Downloader.
    
    This class provides functionality to display the application in the Windows
    system tray with an icon and context menu. It allows users to access
    common functions like opening the web UI, configuring startup settings,
    and exiting the application.
    
    Attributes:
        web_port (int): Port number for the web UI server
        icon (pystray.Icon): System tray icon instance
        running (bool): Flag indicating if the service is running
        app_name (str): Application name used for registry entries and shortcuts
    """
    
    def __init__(self, web_port=8420):
        """
        Initialize the system tray service.
        
        Args:
            web_port (int): Port number for the web UI server
        """
        self.web_port = web_port
        self.icon = None
        self.running = False
        self.app_name = "NazareinsTwitchDownloader"
        
    def start(self):
        """
        Start the system tray service in a separate thread.
        
        On non-Windows platforms, this method will log a message and return False.
        On Windows, it will start a daemon thread to run the system tray icon.
        
        Returns:
            bool: True if the service was started, False otherwise
        """
        if platform.system() != "Windows":
            print("[SystemTray] Not on Windows, system tray disabled")
            return False
            
        self.running = True
        # Start in a separate thread to not block the main application
        tray_thread = threading.Thread(target=self._run_tray)
        tray_thread.daemon = True
        tray_thread.start()
        return True
    
    def stop(self):
        """
        Stop the system tray service.
        
        Stops the system tray icon if it is running and cleans up resources.
        """
        self.running = False
        if self.icon:
            self.icon.stop()
            self.icon = None
        
    def _run_tray(self):
        """
        Run the system tray icon (internal method).
        
        This method loads the icon image, creates the system tray icon with
        a menu, and starts the event loop. It is designed to run in a separate
        thread to avoid blocking the main application.
        """
        try:
            # Load the icon image
            image = self._load_icon_image()
            
            # Create the system tray icon
            self.icon = pystray.Icon(self.app_name)
            self.icon.icon = image
            self.icon.title = "Nazareins Twitch Downloader"
            
            # Set up the menu
            self.icon.menu = self._create_menu()
            
            # Run the icon (this blocks until the icon is stopped)
            self.icon.run()
        except Exception as e:
            print(f"[SystemTray] Error running system tray: {e}")
    
    def _load_icon_image(self):
        """
        Load the custom icon image with fallback mechanisms.
        
        Attempts to load the icon.ico file from various possible locations
        depending on whether the application is running as a frozen executable
        or in a development environment. If the icon cannot be found, a default
        icon is generated.
        
        Returns:
            PIL.Image: The loaded or generated icon image
        """
        try:
            # More comprehensive path list with better debugging
            icon_paths = []
            
            # For frozen app (packaged with PyInstaller)
            if getattr(sys, 'frozen', False):
                base_dir = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable)
                icon_paths.extend([
                    os.path.join(base_dir, "icon.ico"),  # Root of extracted package
                    os.path.join(os.path.dirname(sys.executable), "icon.ico"),  # Executable directory
                    os.path.join(base_dir, "frontend", "build", "icon.ico")  # Original frontend path
                ])
            
            # Standard paths for development environment
            icon_paths.extend([
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "icon.ico"),
                "icon.ico",
                os.path.join("src", "icon.ico"),
                os.path.join("assets", "icon.ico")
            ])
            
            # Try each path with detailed logging
            for i, icon_path in enumerate(icon_paths):
                if os.path.exists(icon_path):
                    return Image.open(icon_path)
            
            # If icon not found, log all attempted paths
            print("[SystemTray] Icon not found in any of these locations:")
            for path in icon_paths:
                print(f"  - {path}")
            print("[SystemTray] Using default icon")
            return self._create_default_icon()
        except Exception as e:
            print(f"[SystemTray] Error loading icon: {e}")
            import traceback
            traceback.print_exc()
            return self._create_default_icon()
    
    def _create_default_icon(self):
        """
        Create a simple default icon as fallback.
        
        Generates a purple circle with a white center as a default icon when
        the application icon cannot be loaded.
        
        Returns:
            PIL.Image: The generated default icon image
        """
        width = 64
        height = 64
        color = (147, 51, 234)  # Purple color from the application
        
        # Create a solid color image
        image = Image.new('RGB', (width, height), color=(0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # Draw a filled circle
        draw.ellipse((4, 4, width-4, height-4), fill=color)
        
        # Draw a small white circle in the center to represent a record button
        draw.ellipse((width//2-8, height//2-8, width//2+8, height//2+8), fill=(255, 255, 255))
        
        return image
    
    def _create_menu(self):
        """
        Create the system tray context menu.
        
        Creates a menu with options to open the web UI, toggle autostart settings,
        and exit the application.
        
        Returns:
            pystray.Menu: The configured system tray menu
        """
        return pystray.Menu(
            pystray.MenuItem("Open Web UI", self._open_web_ui),
            pystray.MenuItem(
                "Start with Windows", 
                self._toggle_autostart,
                checked=lambda item: self._is_autostart_enabled()
            ),
            pystray.MenuItem("Exit", self._exit_app)
        )
    
    def _open_web_ui(self, icon, item):
        """
        Open the web UI in the default browser.
        
        This method is called when the "Open Web UI" menu item is clicked.
        It opens the application's web interface using the system default browser.
        
        Args:
            icon: The system tray icon instance (provided by pystray)
            item: The menu item that was clicked (provided by pystray)
        """
        try:
            url = f"http://localhost:{self.web_port}"
            webbrowser.open(url)
            print(f"[SystemTray] Opening Web UI: {url}")
        except Exception as e:
            print(f"[SystemTray] Error opening Web UI: {e}")
    
    def _toggle_autostart(self, icon, item):
        """
        Toggle the autostart setting.
        
        This method is called when the "Start with Windows" menu item is clicked.
        It toggles between enabling and disabling the application autostart.
        
        Args:
            icon: The system tray icon instance (provided by pystray)
            item: The menu item that was clicked (provided by pystray)
        """
        try:
            if self._is_autostart_enabled():
                self._disable_autostart()
            else:
                self._enable_autostart()
        except Exception as e:
            print(f"[SystemTray] Error toggling autostart: {e}")
    
    def _enable_autostart(self):
        """
        Enable application autostart on Windows.
        
        Registers the application to start automatically when Windows boots.
        Attempts to use Windows shortcuts first (preferred method), with a fallback 
        to registry entry if shortcut creation is not available.
        
        Returns:
            bool: True if successful, False otherwise
        
        Note:
            Only works in frozen application mode, not in development mode.
        """
        try:
            # Get the path to the executable
            if getattr(sys, 'frozen', False):
                # We're running in a PyInstaller bundle
                exe_path = sys.executable
                # Get the directory containing the executable
                exe_dir = os.path.dirname(exe_path)
                
                try:
                    import win32com.client
                    # Get the startup folder path
                    startup_folder = os.path.join(os.environ.get('APPDATA', ''), 
                                                r'Microsoft\Windows\Start Menu\Programs\Startup')
                    shortcut_path = os.path.join(startup_folder, f"{self.app_name}.lnk")
                    
                    # Create the shortcut
                    shell = win32com.client.Dispatch("WScript.Shell")
                    shortcut = shell.CreateShortCut(shortcut_path)
                    shortcut.Targetpath = exe_path
                    shortcut.WorkingDirectory = exe_dir
                    shortcut.save()
                    
                    print(f"[SystemTray] Autostart enabled via shortcut: {shortcut_path}")
                    print(f"[SystemTray] Working directory set to: {exe_dir}")
                    return True
                    
                except ImportError:
                    # Fallback to registry method if win32com is not available
                    reg_command = f'"{exe_path}"'
                    
                    # Open the registry key
                    key = winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                        0, winreg.KEY_SET_VALUE
                    )
                    
                    # Set the registry value
                    winreg.SetValueEx(
                        key, self.app_name, 0, winreg.REG_SZ, reg_command
                    )
                    
                    # Close the key
                    winreg.CloseKey(key)
                    print("[SystemTray] Autostart enabled via registry")
                    return True
            else:
                # We're running in a normal Python environment
                print("[SystemTray] Autostart only available in packaged app")
                return False
        except Exception as e:
            print(f"[SystemTray] Error enabling autostart: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _disable_autostart(self):
        """
        Disable application autostart on Windows.
        
        Removes all autostart configurations for the application, including
        both shortcut and registry-based methods.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check for shortcut in startup folder
            startup_folder = os.path.join(os.environ.get('APPDATA', ''), 
                                         r'Microsoft\Windows\Start Menu\Programs\Startup')
            shortcut_path = os.path.join(startup_folder, f"{self.app_name}.lnk")
            
            if os.path.exists(shortcut_path):
                os.remove(shortcut_path)
                print(f"[SystemTray] Removed startup shortcut: {shortcut_path}")
            
            # Also clean up any registry entries
            try:
                # Open the registry key
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                    0, winreg.KEY_SET_VALUE
                )
                
                # Delete the registry value
                winreg.DeleteValue(key, self.app_name)
                
                # Close the key
                winreg.CloseKey(key)
                print("[SystemTray] Autostart disabled in registry")
            except WindowsError:
                # Key might not exist, which is fine
                pass
                
            return True
        except Exception as e:
            print(f"[SystemTray] Error disabling autostart: {e}")
            return False
    
    def _is_autostart_enabled(self):
        """
        Check if autostart is enabled for the application.
        
        Checks both shortcut and registry-based autostart methods to determine
        if the application is configured to start with Windows.
        
        Returns:
            bool: True if autostart is enabled, False otherwise
        """
        try:
            # Check for shortcut first
            startup_folder = os.path.join(os.environ.get('APPDATA', ''), 
                                         r'Microsoft\Windows\Start Menu\Programs\Startup')
            shortcut_path = os.path.join(startup_folder, f"{self.app_name}.lnk")
            
            if os.path.exists(shortcut_path):
                return True
                
            # Also check registry as fallback
            try:
                # Open the registry key
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                    0, winreg.KEY_READ
                )
                
                # Try to get the registry value
                winreg.QueryValueEx(key, self.app_name)
                winreg.CloseKey(key)
                return True
            except WindowsError:
                return False
        except Exception:
            return False
    
    def _exit_app(self, icon, item):
        """
        Exit the application completely.
        
        This method is called when the "Exit" menu item is clicked.
        It stops the system tray icon and forces the application to exit.
        
        Args:
            icon: The system tray icon instance (provided by pystray)
            item: The menu item that was clicked (provided by pystray)
        """
        self.stop()
        os._exit(0)  # Force exit the application