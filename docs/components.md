```mermaid

classDiagram
    %% Main application components
    class main {
        +asyncio.run(main())
        -setup_services()
        -start_application()
    }
    
    class StreamMonitorService {
        -WebSocketManager websocket_manager
        -EventSubService eventsub_service
        -DownloadService download_service
        -TokenManager token_manager
        +start()
        +stop()
        +restart_eventsub()
        +get_status_summary()
        -_update_all_streamers()
        -_monitoring_loop()
        -_on_token_refresh()
        -_backup_scheduler()
    }
    
    class WebApp {
        -aiohttp.web.Application app
        -WebSocketManager websocket_manager
        +setup_routes(handlers)
        +start(host, port)
        -serve_static_files()
    }
    
    class WebHandlers {
        -WebSocketManager websocket_manager
        -StreamMonitorService monitor_service
        +get_streamers()
        +update_streamers()
        +get_streamer_status()
        +update_streamer_settings()
        +handle_token()
        +handle_twitch_cookie()
        +toggle_downloads()
        +get_eventsub_debug()
        +eventsub_reconnect()
        +start_download()
        +stop_download()
    }
    
    class WebSocketManager {
        -ClientManager app_clients
        -ClientManager console_clients
        -List~Dict~ log_buffer
        +handle_websocket()
        +handle_console_websocket()
        +broadcast_live_status()
        +broadcast_download_status()
        +broadcast_thumbnail_update()
        +broadcast_status_update()
        -send_initial_state()
        -_setup_log_interception()
    }
    
    class EventSubService {
        -TokenManager token_manager
        -String token
        -List~Task~ connection_tasks
        -Dict subscriptions_by_session
        +start()
        +stop()
        +add_streamer_subscription()
        +remove_streamer_subscription()
        +get_status()
        -_handle_connection()
        -_handle_notification()
        -_create_subscription()
        -_unsubscribe_all()
    }
    
    class DownloadService {
        -WebSocketManager websocket_manager
        -TokenManager token_manager
        -Dict active_downloads
        -Set configured_streamers
        +start()
        +start_download()
        +stop_download()
        +enable_downloads()
        -_check_downloads()
        -_download_stream_thread()
        -_download_monitor_loop()
        -_get_auth_token()
    }
    
    class TokenManager {
        -String token_file
        -String refresh_endpoint
        -Dict tokens
        -Task refresh_task
        -List on_token_refresh_callbacks
        +start()
        +stop()
        +get_access_token()
        +refresh_token()
        +validate_token()
        +register_refresh_callback()
        -load_tokens()
        -save_tokens()
        -schedule_refresh_task()
    }
    
    class GQLClient {
        -Dict headers
        -Semaphore _rate_limit_semaphore
        -Dict _cache
        +lookup_channel_ids()
        +check_streams_status()
        +get_channel_info()
        -_fetch_channel_info()
    }
    
    class SystemTrayService {
        -int web_port
        -pystray.Icon icon
        -boolean running
        +start()
        +stop()
        -_run_tray()
        -_create_menu()
        -_open_web_ui()
        -_toggle_autostart()
    }
    
    %% Config and settings
    class settings {
        +CONFIG_DIR
        +get_default_storage_path()
        +get_storage_path()
        +update_storage_path()
        +get_monitored_streamers()
        +update_monitored_streamers()
        +get_streamer_storage_path()
        +update_streamer_storage_path()
    }
    
    %% Relationships
    main --> StreamMonitorService : creates
    main --> WebApp : creates
    main --> SystemTrayService : creates on Windows
    
    StreamMonitorService --> EventSubService : manages
    StreamMonitorService --> DownloadService : manages
    StreamMonitorService --> TokenManager : manages
    StreamMonitorService --> GQLClient : uses
    StreamMonitorService --> settings : reads/writes
    
    WebApp --> WebHandlers : routes to
    WebApp --> WebSocketManager : provides
    
    WebHandlers --> StreamMonitorService : accesses
    WebHandlers --> WebSocketManager : broadcasts through
    WebHandlers --> settings : reads/writes
    
    EventSubService --> TokenManager : uses token
    EventSubService ..> WebSocketManager : sends updates via Monitor
    
    DownloadService --> WebSocketManager : broadcasts status
    DownloadService --> TokenManager : gets auth token
    
    WebSocketManager --> settings : reads streamer data
