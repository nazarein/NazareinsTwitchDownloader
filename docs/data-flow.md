```mermaid

sequenceDiagram
    participant User
    participant Frontend as Frontend (React)
    participant WebServer as Web Server (aiohttp)
    participant WebSocket as WebSocket Manager
    participant Monitor as Stream Monitor Service
    participant EventSub as EventSub Service
    participant Download as Download Service
    participant Twitch as Twitch APIs
    
    %% Initial user interaction
    User->>Frontend: Open application
    Frontend->>WebServer: Request initial state
    WebServer->>WebSocket: Establish WebSocket connection
    WebSocket->>Frontend: Send initial streamer data
    
    %% Adding new streamer
    User->>Frontend: Add streamer
    Frontend->>WebServer: POST /api/streamers
    WebServer->>Monitor: Process new streamer
    Monitor->>Twitch: Lookup channel ID & info
    Twitch-->>Monitor: Return channel data
    Monitor->>EventSub: Create subscription
    EventSub->>Twitch: Subscribe to stream events
    Monitor->>WebSocket: Broadcast streamer added
    WebSocket-->>Frontend: Update UI with new streamer
    
    %% Stream goes live (EventSub notification)
    Twitch->>EventSub: Stream online notification
    EventSub->>Monitor: Update streamer status
    Monitor->>WebSocket: Broadcast live status
    WebSocket-->>Frontend: Update UI (streamer is live)
    
    %% Automatic download (if enabled)
    Monitor->>Download: Check download settings
    alt Downloads enabled
        Download->>Twitch: Start stream capture
        Download->>WebSocket: Broadcast download started
        WebSocket-->>Frontend: Update UI (downloading)
    end
    
    %% Manual user interaction with stream
    User->>Frontend: Toggle download setting
    Frontend->>WebServer: POST /api/streamers/{streamer}/settings
    WebServer->>Monitor: Update streamer settings
    Monitor->>Download: Enable/disable downloads
    Monitor->>WebSocket: Broadcast settings change
    WebSocket-->>Frontend: Update UI with new settings
    
    %% Stream ends
    Twitch->>EventSub: Stream offline notification
    EventSub->>Monitor: Update streamer status
    Monitor->>Download: Stop download (if active)
    Download-->>Monitor: Download completed
    Monitor->>WebSocket: Broadcast stream ended
    WebSocket-->>Frontend: Update UI (streamer offline)
    
    %% Console logging
    WebServer->>WebSocket: Log application events
    WebSocket-->>Frontend: Update console UI