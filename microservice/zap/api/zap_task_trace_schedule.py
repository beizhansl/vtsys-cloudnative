import logging
from typing import List
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from model.zap_task import VtZapTask, TaskStatus, InternStatus
import structlog
from zap_client import handle_zap_task, get_zap_conn
from sqlalchemy.orm import Session
from sqllite_sql import get_db_session
from sqlalchemy import desc

# 初始化调度器
scheduler = BackgroundScheduler()
# 日志相关
# 设置结构化日志
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S%z'
)
logger = structlog.wrap_logger(logging.getLogger())

def get_db_running_task(db_session: Session) -> List[VtZapTask]:
    tasks = db_session.query(VtZapTask).filter(VtZapTask.status==TaskStatus.RUNNING).order_by(desc(VtZapTask.create_time)).all()
    return tasks

def zap_task_trace_task():
    try:
        with get_db_session() as db_session:
            zap = get_zap_conn()
            # 获取任务
            tasks = get_db_running_task(db_session=db_session)
            for task in tasks:
                running_status, msg = handle_zap_task(zap=zap, running_status=task.running_status, target=task.target)
                if running_status == InternStatus.FAILED:
                    task.status = TaskStatus.FAILED
                    task.errmsg = msg
                if running_status == InternStatus.DONE:
                    task.status = TaskStatus.DONE
                    task.finish_time = datetime.now()
                if running_status != task.running_status:
                    task.running_status = running_status
                    db_session.add(task)
            db_session.flush()
       
    except Exception as e:
        logger.error(f"trace zap task error: {e}")

# 添加作业到调度器
scheduler.add_job(zap_task_trace_task, 'interval', seconds=10)