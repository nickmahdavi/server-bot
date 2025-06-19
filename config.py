import os
from dataclasses import dataclass, field

envfield = lambda key, cls=str, default="": field(default_factory=lambda: cls(os.getenv(key, default)))

@dataclass
class Config:
    aws_access_key: str    = envfield("AWS_ACCESS_KEY_ID")
    aws_secret_key: str    = envfield("AWS_SECRET_ACCESS_KEY")
    aws_region: str        = envfield("AWS_REGION", default="us-east-1")
    aws_instance_id: str   = envfield("AWS_INSTANCE_ID")
    aws_instance_type: str = envfield("AWS_INSTANCE_TYPE", default="m7i.large")
    
    server_address: str    = envfield("SERVER_ADDRESS", default="localhost")
    server_port: int       = envfield("SERVER_PORT", cls=int, default=25565)
    
    discord_bot_token: str = envfield("DISCORD_BOT_TOKEN")
    admin_user_id: str     = envfield("ADMIN_USER_ID")
    admin_username: str    = envfield("ADMIN_USERNAME")

    min_players: int           = 1
    shutdown_delay: int        = 1800 # 30 minutes
    backup_interval: int       = 86400 # 24 hours
    check_active_interval: int = 60 # 1 minute
    check_lobby_interval: int  = 1 # 1 second
    max_attempts: int          = 60 # 1 minute

    webhook_host: str = envfield("WEBHOOK_HOST", default="localhost")
    webhook_port: int = envfield("WEBHOOK_PORT", cls=int, default=8080)