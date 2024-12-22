from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Text, Table, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timezone
from basemodel import Base

# Assuming these are the translation of the Django model's verbose names to descriptions for SQLAlchemy
# from enum import Enum as PyEnum


class TaskStatus(Enum):
    RUNNING = 'Running'
    DONE = 'Done'
    FAILED = 'Failed'
    ERROR = 'Error'


class InternStatus(Enum):
    SPIDER = 'spider'
    AJAXSPIDER = 'ajaxspider'
    ACTIVE = 'active'
    PASSIVE = 'passive'
    DONE = 'done'
    FAILED = 'failed'


class VtZapTask(Base):
    __tablename__ = 'vt_zap_task'

    id = Column(Integer, primary_key=True)
    target = Column(String(256), nullable=False)
    status = Column(Enum(TaskStatus), default=TaskStatus.RUNNING)
    create_time = Column(DateTime, default=datetime.now(timezone.utc))
    finish_time = Column(DateTime, nullable=True)
    update_time = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    running_status = Column(Enum(InternStatus), nullable=False, default=InternStatus.SPIDER)
    running_id = Column(String(256), nullable=True)
    errmsg = Column(String(256), nullable=True)
    
    def __repr__(self):
        return f"<VtZapTask(name={self.id})>"
