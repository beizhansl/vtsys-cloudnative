from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Text, Table, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timezone
from basemodel import Base

# Assuming these are the translation of the Django model's verbose names to descriptions for SQLAlchemy
# from enum import Enum as PyEnum

class TaskType(Enum):
    DISTRIBUTED = 'distributed'
    SINGLE = 'single'
    SUBTASK = 'subtask'


class TaskStatus(Enum):
    RUNNING = 'Running'
    DONE = 'Done'
    FAILED = 'Failed'
    ERROR = 'Error'


class VtOpenvasTask(Base):
    __tablename__ = 'vt_openvas_task'

    id = Column(Integer, primary_key=True)
    
    task_type = Column(Enum(TaskType), default=TaskType.SINGLE, nullable=False)
    status = Column(Enum(TaskStatus), default=TaskStatus.RUNNING)
    create_time = Column(DateTime, default=datetime.now(timezone.utc))
    finish_time = Column(DateTime, nullable=True)
    update_time = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    running_id = Column(String(36), nullable=True, default='')
    scanners_str = Column(String(256)) # 对于distributed记录所有地址, 已','分隔
    
    def __repr__(self):
        return f"<VtOpenvasTask(name={self.id})>"
