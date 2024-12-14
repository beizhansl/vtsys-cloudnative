from sqlalchemy import create_engine, Column, Integer, String, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from enum import Enum as PyEnum
from contextlib import contextmanager
import os
from model.basemodel import Base

# 获取环境变量或设置默认值
def get_db_url():
    # 从环境变量中获取数据库配置
    db_user = os.getenv("DB_USER", "root")
    db_password = os.getenv("DB_PASSWORD", "")
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "4000")
    db_name = os.getenv("DB_NAME", "test")
    return f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

# 创建数据库引擎
engine = create_engine(get_db_url(), pool_recycle=3600)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@contextmanager
def get_db_session():
    """提供一个事务性的数据库会话"""
    db_session = SessionLocal()
    try:
        yield db_session
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise
    finally:
        db_session.close()

# 初始化数据库（如果表不存在则创建）
Base.metadata.create_all(bind=engine)


# if __name__ == "__main__":
#     with get_db_session() as db_session:
#         # 添加一些测试任务
#         new_task1 = Task(name="Task One", description="First task", status=TaskStatus.PENDING)
#         new_task2 = Task(name="Task Two", description="Second task", status=TaskStatus.IN_PROGRESS)
#         new_task3 = Task(name="Task Three", description="Third task", status=TaskStatus.PENDING)
        
#         db_session.add_all([new_task1, new_task2, new_task3])

#         # 获取并打印所有等待中的任务
#         pending_tasks = get_pending_tasks(db_session)
#         for task in pending_tasks:
#             print(f"Task ID: {task.id}, Name: {task.name}, Description: {task.description}")