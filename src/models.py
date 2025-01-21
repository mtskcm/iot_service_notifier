from pydantic import BaseModel, AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional, Union


# Pydantic model for Notification
class Notification(BaseModel):
    """
    Represents a notification model for sending alerts.
    """
    urls: Union[AnyUrl, List[AnyUrl]]
    title: str = 'Alert'
    body: str
    attachments: Optional[List[Union[str, AnyUrl]]] = None

class Settings(BaseSettings):
    """
    Represents the application settings loaded from environment variables.
    """
    broker: str
    port: int = 1883
    user: Optional[str] = None
    password: Optional[str] = None
    base_topic: str
    status_topic: str
    pushsafer_key: str
    influxdb_url: str
    influxdb_token: str
    influxdb_org: str
    influxdb_bucket: str

    model_config = SettingsConfigDict(
        env_prefix='NOTIFIER_',
        env_file="../local.env",
        env_file_encoding='utf-8'
    )