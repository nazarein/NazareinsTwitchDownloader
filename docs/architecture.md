```mermaid

flowchart TD
    %% Main entry points and initialization
    Main[main.py] --> WebApp
    Main --> StreamMonitorService
    Main --> |Windows Only| SystemTrayService
    
    %% Core services
    subgraph Services
        StreamMonitorService --> EventSubService
        StreamMonitorService --> DownloadService
        StreamMonitorService --> TokenManager
        StreamMonitorService --> GQLClient
        
        EventSubService -- "Live Status\nNotifications" --> TwitchEventSub[Twitch EventSub WebSockets]
        DownloadService -- "Stream\nCapture" --> Streamlink
        TokenManager -- "Authentication" --> TwitchAuth[Twitch OAuth API]
        GQLClient -- "Channel Info\nQuery" --> TwitchGQL[Twitch GraphQL API]
    end
    
    %% Web Application components
    subgraph WebApplication
        WebApp --> WebHandlers
        WebApp --> |Routes| WebSocketManager
        WebHandlers -- "Request Processing" --> StreamMonitorService
        WebSocketManager -- "Real-time\nUpdates" --> Clients
    end
    
    %% Data storage
    subgraph Configuration
        Settings[settings.py] -- "Read/Write" --> ConfigFiles[(Configuration Files)]
        StreamMonitorService --> Settings
        WebHandlers --> Settings
    end
    
    %% Frontend communication
    WebSocketManager -- "Status Updates" --> FrontendWS[Frontend WebSockets]
    WebSocketManager -- "Console Logs" --> ConsoleLogs[Console WebSocket]
    
    %% User interactions
    User(User) -- "Web UI\nInteraction" --> WebHandlers
    User -- "Views Streams" --> FrontendWS
    
    %% Stream processing flow
    EventSubService -- "Stream Online" --> StreamMonitorService
    StreamMonitorService -- "Start Download" --> DownloadService
    DownloadService -- "Save Stream" --> Filesystem[(File System)]
    
    %% Authentication flow
    User -- "OAuth Login" --> TokenManager
    User -- "Cookie Auth" --> DownloadService
    
    %% Style definitions
    classDef main fill:#f96,stroke:#333,stroke-width:2px;
    classDef service fill:#bbf,stroke:#333;
    classDef web fill:#bfb,stroke:#333;
    classDef storage fill:#fbb,stroke:#333;
    classDef external fill:#ddd,stroke:#333,stroke-dasharray: 5 5;
    classDef user fill:#fcf,stroke:#333;
    
    %% Apply styles
    class Main main;
    class StreamMonitorService,EventSubService,DownloadService,TokenManager,GQLClient,SystemTrayService service;
    class WebApp,WebHandlers,WebSocketManager web;
    class Settings,ConfigFiles,Filesystem storage;
    class TwitchEventSub,TwitchAuth,TwitchGQL,Streamlink external;
    class User,Clients,FrontendWS,ConsoleLogs user;
