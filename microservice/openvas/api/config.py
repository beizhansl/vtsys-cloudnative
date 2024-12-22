import logging
from pydantic import Field
from pydantic_settings import BaseSettings
from enum import Enum

# 配置文件相关
class Settings(BaseSettings):
    manager_ips: list = []
    gvmdtype: str
    unixsockpath: str = None
    tlscapath: str = None
    tlscertpath: str = None
    tlskeypath: str = None
    username: str
    password: str
    logfile:str
    clientport:int
    gvmdhost: str = "127.0.0.1"
    gvmdport: int = 9390
    max_task_num: int = 10
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()

# 日志相关
logger = logging.getLogger()
logger.setLevel(logging.INFO)
fh = logging.FileHandler(filename=settings.logfile)
formatter = logging.Formatter(
    "%(asctime)s - %(module)s - %(funcName)s - line:%(lineno)d - %(levelname)s - %(message)s"
)
fh.setFormatter(formatter)
logger.addHandler(fh) #将日志输出至文件


# 错误码
class Errcode(Enum):
    CONNERR = 1
    
    def description(self):
        if self == Errcode.CONNERR:
            return "Connecte to openvas failed"
