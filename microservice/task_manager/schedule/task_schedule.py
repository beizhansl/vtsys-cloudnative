from copy import deepcopy
from typing import Dict, List
from apscheduler.schedulers.blocking import BlockingScheduler
import logging
import structlog
from datetime import datetime
from ..model import task as Task, report as Report, scanner as Scanner
import os
from ..tidb_sql import get_db_session
import requests
from sqlalchemy import Enum, Row, Tuple, and_, func
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
    content = None
    try:
        content = fetch_report(url, task_id)
    except Exception as e:
        logger.error(f"fetch report error: {e}")
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

def trace_task(dbsession: Session, task:Task.VtTask, update_scanner_dict: dict):
    logger.info(f"Tracing task {task.id}")
    ipaddr = task.scanner.ipaddr
    port = task.scanner.port
    task_id = task.task_id
    url = f"http://{ipaddr}:{port}"
    status  = None
    try:
        status, msg = fetch_status(url, task_id)
    except Exception as e:
        logger.error(f"fetch status error: {e}")
    # 统计scanner/task失败次数，达到5次则直接reload
    old_scanner = deepcopy(task.scanner)
    old_task = deepcopy(task)
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
    # 判断scanner是否需要更新
    if old_scanner.except_num != task.scanner.except_num:
        update_scanner_dict[task.scanner.id] = task.scanner.except_num
        dbsession.add(task.scanner)
    # 判断task是否需要更新
    if old_task.except_num != task.except_num or \
        old_task.task_status != task.task_status:
            dbsession.add(task)

def trace_tasks():
    logger.info("Tracing tasks")
    try:
        with get_db_session() as db_session:
            update_scanner_dict = {}
            running_tasks = get_running_tasks(db_session=db_session)
            for running_task in running_tasks:
                if running_task.scanner.status == Scanner.Status.DELETED:
                    reload_task(running_task)
                    db_session.add(running_task)
                    continue
                trace_task(db_session, running_task, update_scanner_dict)
            # 目前两个scanner表共用
            # if update_scanner_dict:
            #     try:
            #         post_resource_scanners(update_scanner_dict)    
            #     except Exception as e:
            #         logger.error(f"post resource scanners error: {e}")
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
            count: 1, 表示scanner数量
            scanners: [{
                "scanner": "",  scanner详细信息
            }] 具体的scanner列表
            errmsg: 错误原因
        }
    """
    response = requests.get(
        resourceControllerUrl + '/list_scanner_resource',
    )
    response.raise_for_status()
    data = response.json()
    if not data['ok']:
        logger.error(f"Get scanner resources failed, {data['errmsg']}")
        return None
    scanners = data['scanners']
    count = data['count']
    return count, scanners 

@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(3),
    retry=(retry_if_exception_type(requests.exceptions.Timeout) | retry_if_exception_type(requests.exceptions.ConnectionError)),
    retry_error_callback=handle_retry_error
)
def post_resource_scanners(scanner_dict: Dict[int, int]):
    """
        更新资源管理模块的scanner, 主要是except_num
        reponse:
        {
            ok: False/True, 为False表明资源管理模块出现问题
            errmsg: 错误原因
        }
    """
    response = requests.post(
        resourceControllerUrl + '/update_resource_scanner',
        json=scanner_dict
    )
    response.raise_for_status()
    data = response.json()
    if not data['ok']:
        logger.error(f"Update scanner resource failed, {data['errmsg']}")
        return False
    return True

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
    ok = False
    try:
        ok = post_task(scanner_url, task.target, task.id)
    except Exception as e:
        logger.error(f"post task error: {e}")
    if not ok:
        scanner.except_num += 1
        return False
    scanner.except_num = 0
    task.scanner = scanner
    task.scanner_id = scanner.id
    task.task_status = Task.Status.RUNNING
    return True

def get_scanners(db_session: Session) -> List[Scanner.VtScanner]:
    return db_session.query(Scanner.VtScanner).filter(Scanner.Status.ENABLE).all()

def get_task_scanners(db_session: Session) -> List[Row[Tuple[int, int, int]]]:
    # 查询每个 scanner 及其可以并发执行的任务数与已分配的 running 状态任务数
    query = (
        db_session.query(
            Scanner.VtScanner.id,
            Scanner.VtScanner.engine,
            Scanner.VtScanner.max_concurrency,
            func.count(Task.id).label('running_tasks')  # 计算已分配且状态为 running 的任务数量
        )
        .outerjoin(
            Task.VtTask, 
            and_(Task.VtTask.scanner_id == Scanner.VtScanner.id, Task.VtTask.task_status == Task.Status.RUNNING)  # 左外连接并过滤 running 状态的任务
        )
        .group_by(Scanner.VtScanner.id)  # 按照 scanner 分组
    )
    return query.all()

def check_scanner_diff(old_scanner, new_scanner):
    if old_scanner.except_num != new_scanner.except_num:
        return True
    return False

def distribute_tasks():
    logger.info("Distributing tasks")
    # 从资源控制器获取资源来分发
    # 目前使用同一个数据库, 因此可以直接从数据库中获取
    # 获取scanner，按照使用率进行排名
    # scanners_available = None
    # try:
    #     scanners_available = fetch_scanner_resource()
    # except Exception as e:
    #     logger.error(f"fetch scanner resource error: {e}")
    # if scanners_available == None:
    #     return
    try:
        with get_db_session() as db_session:
            update_scanner_dict:Dict[int, int] = {}
            scanners_available = get_task_scanners()
            scanners:List[Scanner.VtScanner] = get_scanners()
            scanner_dict:Dict[int, Scanner.VtScanner] = {}
            for scanner in scanners:
                scanner_dict[scanner.id] = scanner
            # 统计不同类别的scanner还可以分配的task数量
            task_num_scanners = {}
            for scanner_id, engine, parallel, running in scanners_available:
                if parallel == 0 or parallel == running:
                    continue
                if engine in task_num_scanners:
                    task_num_scanners[engine][0] += parallel-running
                    task_num_scanners[engine][1].append((scanner_id, parallel-running, parallel))
                else:
                    task_num_scanners[engine] = [parallel-running, [(scanner_id, parallel-running, parallel)]]
            # 获取各个engine的queued task
            for engine in task_num_scanners:
                can_apply_task_num = task_num_scanners[engine] 
                wait_tasks = get_queued_tasks(db_session=db_session, scan_engine=engine, num=can_apply_task_num)
                scanners_sorted:List[Tuple] = task_num_scanners[engine][1]
                # 按照使用率从低到高分发
                index = 0
                while index < len(wait_tasks):
                    wait_task = wait_tasks[index]
                    if len(scanners_sorted) == 0:
                        break
                    scanners_sorted.sort(
                        key=lambda x: (x[1] / x[2]) if x[2] > 0 else 0,
                    )
                    scanner_chosed = scanners_sorted[0]
                    # 可能出现scanner故障，剩余scanner不够用
                    if scanner_chosed[1] == scanner_chosed[2]:
                        break
                    scanner = scanner_dict[scanner_chosed[0]]
                    old_scanner = deepcopy(scanner)
                    ok = distribute_task(scanner, wait_task)
                    if check_scanner_diff(old_scanner, scanner):
                        update_scanner_dict[scanner.id] = scanner.except_num
                        db_session.add(scanner)
                    if ok:
                        scanners_sorted[0][1] += 1
                        index += 1
                        db_session.add(wait_task)
                    else: # scanner存在问题先不分发
                        scanners_sorted.pop(0)
                        logger.warn(f"scanner {scanner.name} post task error, skip...")
            # if update_scanner_dict:
            #     try:
            #         post_resource_scanners(update_scanner_dict)    
            #     except Exception as e:
            #         logger.error(f"post resource scanners error: {e}")                      
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
    logger.info("Starting task scheduler...")
    try:
        scheduler.start()
        logger.info("Started task scheduler...")
    except (KeyboardInterrupt, SystemExit):
        pass
    logger.info("Stopped task scheduler...")
