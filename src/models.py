from pydantic import BaseModel, AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional, Union


# Pydantic model for Notification
class Notification(BaseModel):
    """
    Represents a notification model for sending alerts.
    """
    urls: AnyUrl | list[AnyUrl]
    title: str = 'Alert'
    body: str
    attachments: list | None = None

