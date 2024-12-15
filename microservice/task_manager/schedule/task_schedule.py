from apscheduler.schedulers.blocking import BlockingScheduler
import logging
import structlog
from datetime import datetime
from model import task as Task, report as Report, scanner as Scanner
import os
from tidb_sql import get_db_session
import requests
from sqlalchemy import Enum
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
# from kubernetes import client as k8s_client

# 设置结构化日志
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S%z'
)
logger = structlog.wrap_logger(logging.getLogger())
# 获取资源管理器的地址
resourceControllerHost = os.getenv("RESOURCE_CONTROLLER_HOST", "localhost")
resourceControllerPort = os.getenv("RESOURCE_CONTROLLER_PORT", "4000")
resourceControllerUrl = f"http://{resourceControllerHost}:{resourceControllerPort}"

def get_running_tasks(db_session: Session):
    return db_session.query(Task.VtTask).filter(Task.VtTask.task_status == Task.Status.RUNNING).all()

def handle_retry_error(retry_state):
    logger.error(f"All retries failed with exception: {retry_state.outcome.exception()}")
    raise None

class InternStatus(Enum):
        ERROR = 'Error'
        RUNNING = 'Running'
        DONE = 'Done'
        FAILED = 'Failed'

@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(3),
    retry=(retry_if_exception_type(requests.exceptions.Timeout) | retry_if_exception_type(requests.exceptions.ConnectionError)),
    retry_error_callback=handle_retry_error
)
def fetch_status(url, task_id):
    """
        reponse:
        {
            ok: False/True, 为False表明扫描引擎出现问题
            errmsg: 错误原因
            running_status: 任务状态, Running / Done / Failed / Error
        }
    """
    response = requests.get(
        url + '/get_task',
        params={'running_id': task_id},
    )
    response.raise_for_status()
    data = response.json()
    msg = None
    if not data['ok']:
        msg = data['errmsg']
        logger.error(f"Get task from scanner {url} failed, {msg}")
        return None, msg
    status = data['running_status']
    return status, msg

@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(3),
    retry=(retry_if_exception_type(requests.exceptions.Timeout) | retry_if_exception_type(requests.exceptions.ConnectionError)),
    retry_error_callback=handle_retry_error
)
def fetch_report(url, task_id):
    """
        reponse:
        {
            ok: False/True, 为False表明扫描引擎出现问题
            errmsg: 错误原因
            content: 文件内容
        }
    """
    response = requests.get(
        url + '/get_report',
        params={'running_id': task_id},
    )
    response.raise_for_status()
    data = response.json()
    if not data['ok']:
        logger.error(f"Get report from scanner {url} failed, {data['errmsg']}")
        return None
    content = data['content']
    # content = base64.b64decode(content)
    return content

def reload_task(task:Task.VtTask):
    logger.info(f"Reloading task {task.id}")
    task.running_id = None
    task.scanner_id = None
    task.scanner = None
    task.task_status = Task.Status.QUEUED
    task.except_num = 0

def download_report(task:Task.VtTask):
    logger.info(f"Downloading task {task.id}")
    ipaddr = task.scanner.ipaddr
    port = task.scanner.port
    task_id = task.task_id
    url = f"http://{ipaddr}:{port}"
    content, msg = fetch_report(url, task_id)
    if content == None:
            return None
    time = datetime.now().strftime("%Y%m%d%H%M%S")
    typeF = task.scanner.filename
    filename = task.name+'_'+time+typeF
    size = len(content)
    new_report = Report.VtReport(
                        filename=filename, size=size, type=typeF, 
                        task=task, task_id=task.id, content=content
                        )
    return new_report    

def trace_task(dbsession: Session, task:Task.VtTask):
    logger.info(f"Tracing task {task.id}")
    ipaddr = task.scanner.ipaddr
    port = task.scanner.port
    task_id = task.task_id
    url = f"http://{ipaddr}:{port}"
    status, msg = fetch_status(url, task_id)
    # 统计scanner/task失败次数，达到5次则直接reload
    if status == None:
        task.except_num += 1
        task.scanner.except_num += 1
        if task.except_num == 5:
            reload_task(task)
    if status == InternStatus.ERROR:
        task.scanner.except_num += 1
        reload_task(task)
    if status == InternStatus.FAILED:
        task.task_status = Task.Status.FAILED
        task.except_num = 0
        task.errmsg = msg
    if status == InternStatus.DONE:
        report = download_report(task)
        if report == None:
            task.except_num += 1
            task.scanner.except_num += 1
            if task.except_num == 5:
                reload_task(task)
            return
        task.scanner.except_num = 0
        task.except_num = 0
        task.report = report
        task.task_status = Task.Status.DONE
        dbsession.add(report)
        # dbsession.flush()
        # task.report_id = report.id
    if status == InternStatus.RUNNING:
        task.scanner.except_num = 0
        task.except_num = 0

def trace_tasks():
    logger.info("Tracing tasks")
    try:
        with get_db_session() as db_session:
            running_tasks = get_running_tasks(db_session=db_session)
            for running_task in running_tasks:
                if running_task.scanner.status == Scanner.Status.DELETED:
                    reload_task(running_task)
                    db_session.add(running_task)
                    continue
                trace_task(db_session, running_task)
                
    except Exception as e:
        logger.error(f"Dbsession save {db_session} exception: {e}")

def get_queued_tasks(db_session: Session, scan_engine: str, num: int):
    return db_session.query(Task.VtTask).filter(
                            Task.VtTask.task_status == Task.Status.RUNNING, 
                            Task.VtTask.scanner_type == scan_engine
                            ).order_by('-priority', 'create_time').limit(num).all()

@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(3),
    retry=(retry_if_exception_type(requests.exceptions.Timeout) | retry_if_exception_type(requests.exceptions.ConnectionError)),
    retry_error_callback=handle_retry_error
)
def fetch_scanner_resource():
    """
        reponse:
        {
            ok: False/True, 为False表明资源管理模块出现问题
            scanners: [{
                "scanner": "",  scanner详细信息
                "num": "",  还可执行的任务数
            }] 具体的scanner列表
            errmsg: 错误原因
        }
    """
    response = requests.get(
        resourceControllerUrl + '/get_scanner_resource',
    )
    response.raise_for_status()
    data = response.json()
    if not data['ok']:
        logger.error(f"Get scanner resources failed, {data['errmsg']}")
        return None
    scanners = data['scanners']
    return scanners 

@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(3),
    retry=(retry_if_exception_type(requests.exceptions.Timeout) | retry_if_exception_type(requests.exceptions.ConnectionError)),
    retry_error_callback=handle_retry_error
)
def post_task(scanner_url, target, task_id):
    """
        reponse:
        {
            ok: False/True, 为False表明扫描引擎出现问题
            errmsg: 错误原因
        }
    """
    response = requests.post(
        scanner_url + '/create_task',
        params={'target': target, 'task_id': task_id}
    )
    response.raise_for_status()
    data = response.json()
    ok = data['ok']
    if not ok:
        logger.error(f"Create task {scanner_url} failed, {data['errmsg']}")
    return ok

def distribute_task(scanner:Scanner.VtScanner, task:Task.VtTask):
    scanner_url = f'http://{scanner['ipaddr']}:{scanner['port']}'
    ok = post_task(scanner_url, task.target, task.id)
    if not ok:
        scanner.except_num += 1
        return
    scanner.except_num = 0
    task.scanner = scanner
    task.scanner_id = scanner.id
    task.task_status = Task.Status.RUNNING    

def distribute_tasks():
    logger.info("Distributing tasks")
    # 从资源控制器获取资源来分发
    scanners = fetch_scanner_resource()
    if scanners == None:
        return
    for scanner_msg in scanners:
        try:
            with get_db_session() as db_session:
                scanner = scanner_msg['scanner']
                can_apply_task_num = scanner_msg['num'] 
                scanner_engine = scanner['engine']
                wait_tasks = get_queued_tasks(db_session=db_session, scan_engine=scanner_engine, num=can_apply_task_num)
                for wait_task in wait_tasks:
                    distribute_task(scanner, wait_task)
        except Exception as e:
            logger.error(f"Dbsession save {db_session} exception: {e}")

def task_schedule():
    # 周期性执行任务逻辑
    # 扫描任务表
    # 1. 分发排队中的任务
    # 2. 追踪运行中的任务
    #   2.1. 任务完成后下载任务报告
    #   2.2. 任务因扫描器宕机等原因执行失败则重新排队任务
    logger.info("Executing the task periodic task")
    trace_tasks()
    distribute_tasks()
    

if __name__ == "__main__":
    scheduler = BlockingScheduler()
    scheduler.add_job(task_schedule, 'interval', seconds=60)  # 每60秒执行一次
    print("Starting task scheduler...")
    try:
        scheduler.start()
        print("Started task scheduler...")
    except (KeyboardInterrupt, SystemExit):
        pass
    print("Stopped task scheduler...")