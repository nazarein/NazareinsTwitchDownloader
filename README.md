
# Nazarein's Twitch Downloader

Never miss a stream again with this Twitch livestream downloader.



## Features

- 🌐 **Web Interface**: Runs on Windows or Linux as a web app. On Windows, it runs in the system tray, and on Linux, it runs as a Docker container.
- 📡 **Live Stream Detection**: Uses EventSub for updates, ensuring accurate live status detection (token login required for optimal functionality).
- 🎥 **Ad-Free Downloads**: Cookie login enables ad-free viewing with an active Twitch subscription or Twitch Turbo.
- 🔄 **Automatic Recording**: Automatically starts downloads when streams go live, based on saved settings.

---

## Installation Methods

Choose your preferred installation method:

### Method 1: Using the Installer
1. Download `NazareinsTwitchDownloader_Setup.exe` from the [Releases](https://github.com/nazarein/NazareinsTwitchDownloader/releases) page.
2. Run the installer.
3. Follow the installation wizard.
4. Launch Nazarein's Twitch Downloader from your Start Menu or Desktop.

### Method 2: Standalone Executable
1. Download `NazareinsTwitchDownloader.exe` from the [Releases](https://github.com/nazarein/NazareinsTwitchDownloader/releases) page.
2. Place the file wherever you want.
3. Double-click to run.

### Method 3: Running from Source
You'll need Git and Python 3.11 or higher installed.

```bash
# Clone the repository
git clone https://github.com/nazarein/NazareinsTwitchDownloader.git
cd NazareinsTwitchDownloader

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

### Method 4: Docker Container(preferred method)
1. Install Docker ([Docker Engine Installation](https://docs.docker.com/engine/install)).
2. Clone the repository:
   ```bash
   git clone https://github.com/nazarein/NazareinsTwitchDownloader.git
   cd NazareinsTwitchDownloader
   docker compose up -d
   ```
   *Note*: Modify mount points in `docker-compose.yml` to fit your setup.

---

## System Requirements

- Windows 10, 11 or Linux  
- 100MB free disk space  
- Internet connection  
- Git (only for running from source and Docker)  
- Python 3.11+ (only for running from source)  
- Docker (only for running as a container)

---

## Usage

### Basic Setup

1. Open the application in your browser at `http://localhost:8420` or use the IP of your Linux server if not on your local machine.
2. Add Twitch broadcasters you want to save.
3. Login with your Twitch account for optimal stream detection using EventSub.
4. Use cookie login for ad-free viewing with an active Twitch subscription or Turbo.
5. Enable automatic downloads for each streamer with applied settings.


---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---