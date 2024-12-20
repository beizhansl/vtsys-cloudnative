import logging
from pydantic import Field
from pydantic_settings import BaseSettings
from enum import Enum

# 配置文件相关
class Settings(BaseSettings):
    scanner_namespace: str
    manager_namespace: str
    cpu_hwl: int
    cpu_lwl: int
    memory_hwl: int
    memory_lwl: int
        
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()