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

class VtOpenvasTask(Base):
    __tablename__ = 'vt_openvas_task'

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    type = Column(Enum(TaskType), nullable=False)
    task_type = Column(Enum(TaskType), default=TaskType.SINGLE, nullable=False)
    create_time = Column(DateTime, default=datetime.now(timezone.utc))
    finish_time = Column(DateTime, nullable=True)
    update_time = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    running_id = Column(String(36), nullable=True, default='')
    parallels = Column(String(256)) # 对于distributed记录所有地址
    
    def __repr__(self):
        return f"<VtOpenvasTask(name={self.id})>"
