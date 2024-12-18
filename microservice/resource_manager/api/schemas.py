from pydantic import BaseModel, Field
from enum import Enum
from typing import List, Optional
from datetime import datetime
import base64

class ScannerType(str, Enum):
    WEB = 'web'
    HOST = 'host'


class ScannerEngine(str, Enum):
    ZAP = 'zaproxy'
    OPENVAS = 'openvas'


class FileType(Enum):
    HTML = 'html'
    PDF = 'pdf'
    XML = 'xml'


class VtScannerSchema(BaseModel):
    id: int
    name: str
    type: ScannerType
    engine: ScannerEngine
    ipaddr: str
    port: str
    filetype: FileType
    max_concurrency: int
    except_num: int
    
    class Config:
        orm_mode = True


class VtScannerListResponse(BaseModel):
    count: int
    scanners: List[VtScannerSchema]
