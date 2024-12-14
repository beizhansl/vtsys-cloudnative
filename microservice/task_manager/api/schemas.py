from pydantic import BaseModel, Field
from enum import Enum
from typing import List, Optional
from datetime import datetime
import base64

class TaskType(str, Enum):
    WEB = 'web'
    HOST = 'host'


class ScannerEngine(str, Enum):
    ZAP = 'zaproxy'
    OPENVAS = 'openvas'


class Status(str, Enum):
    QUEUED = 'queued'
    RUNNING = 'running'
    DONE = 'done'
    FAILED = 'failed'


class VtTaskSchema(BaseModel):
    id: int
    name: str
    priority: int
    target: str
    type: TaskType
    scanner_type: ScannerEngine
    task_status: Status
    scanner_id: Optional[int]
    user_id: str
    create_time: datetime
    finish_time: datetime
    update_time: datetime
    
    class Config:
        orm_mode = True


class VtTaskListResponse(BaseModel):
    total: int
    count: int
    page_num: int
    page_size: int
    tasks: List[VtTaskSchema]


class VtTaskCreateRequest(BaseModel):
    target: str = Field(..., description="The target of the task")
    type: TaskType = Field(..., description="The type of the task")
    engine: ScannerEngine = Field(..., description="The scanner engine to use")
    name: str = Field(..., description="The name of the task")
    remark: str = Field("", description="The remark of the task")
    parallel: int = Field(1, description="The parallel the task")
    
    class Config:
        orm_mode = True   


class VtTaskCreateResponse(BaseModel):
    success: bool
    task: VtTaskSchema


class VtReportResponse(BaseModel):
    filename = str
    type = str
    content = str
    size = int
    create_time = datetime
    
    class Config:
        orm_mode = True


class VtTaskCountSchema(BaseModel):
    scanner_type: str
    num: int


class VtTaskCountResponse(BaseModel):
    type_num: int
    task_count: List[VtTaskCountSchema]
