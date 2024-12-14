from apscheduler.schedulers.blocking import BlockingScheduler
import logging
import structlog
from datetime import datetime
from model import scanner as Scanner
import os
from tidb_sql import get_db_session
import requests
from sqlalchemy import Enum
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
# from kubernetes import client as k8s_client
from k8s_client import load_kube_config
from kubernetes import client
from kubernetes.client import V1PodList
from kubernetes.client.rest import ApiException

# 设置结构化日志
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S%z'
)
logger = structlog.wrap_logger(logging.getLogger())
# 获取资源管理器的地址
taskControllerHost = os.getenv("RESOURCE_CONTROLLER_HOST", "localhost")
taskControllerPort = os.getenv("RESOURCE_CONTROLLER_PORT", "4000")
taskControllerUrl = f"http://{taskControllerHost}:{taskControllerPort}"

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



def get_db_scanners(db_session: Session):
    query = (
        db_session.query(Scanner.VtScanner)
        .filter(Scanner.VtScanner.status.in_([Scanner.Status.DISABLE, Scanner.Status.ENABLE]))
    )
    return query.all()

def fetch_scanners():
    v1 = client.CoreV1Api()
    # 首先获取所有负责scale的scanner的scaler
    scanners = []
    try:
        label_selector = "type=scanner,group=vtscan"
        pods:V1PodList = v1.list_pod_for_all_namespaces(label_selector=label_selector, watch=False)
        for pod in pods.items:
            scanners.append({
                'name': pod.metadata.name,
                'labels': pod.metadata.labels,
                'status': pod.status.phase,
                'ipaddress': pod.status.pod_ip,
            })
    except ApiException as e:
        logger.error(f"Exception when calling CoreV1Api->list_pod_for_all_namespaces: {e}\n")
        return False, []
    return True, scanners

def fetch_scanner_scalers():
    v1 = client.CoreV1Api()
    # 首先获取所有负责scale的scanner的scaler
    scanner_scalers = []
    try:
        label_selector = "type=scanner_scaler,group=vtscan"
        pods:V1PodList = v1.list_pod_for_all_namespaces(label_selector=label_selector, watch=False)
        for pod in pods.items:
            scanner_scalers.append({
                'name': pod.metadata.name,
                'labels': pod.metadata.labels,
                'status': pod.status.phase
            })
    except ApiException as e:
        logger.error(f"Exception when calling CoreV1Api->list_pod_for_all_namespaces: {e}\n")
    return scanner_scalers
    
        

def trace_scanners():
    logger.info("Tracing tasks")
    try:
        with get_db_session() as db_session:
            # 获取数据库中运行中（enable/disable）的扫描器
            db_scanners = get_db_scanners()
            # 从k8s获取所有运行中scanner
            
    except Exception as e:
        logger.error(f"Dbsession save {db_session} exception: {e}")


def my_task():
    # 周期性执行任务逻辑
    # 扫描任务表
    # 1. 扩缩容
    #   1.1. 扩容，VPA/HPA
    #   1.2. 缩容，VPA/HPA，enable->disable->deleted
    #                                     ->enable ?
    # 2. 追踪扫描器
    #   2.1. 对比kubernetes正在运行中的和数据库中的扫描器
    #   2.2. 进行健康检测，将标记为非健康状态的扫描器下线
    logger.info("Executing the resource periodic task")
    trace_scanners()
    # autoscale_scanner()


if __name__ == "__main__":
    # 首先自动加载配置
    try:
        load_kube_config()
        logger.info("Loaded k8s configuration.")
    except Exception as e:
        logger.error((e))
        raise
    scheduler = BlockingScheduler()
    scheduler.add_job(my_task, 'interval', seconds=60)  # 每60秒执行一次
    print("Starting resource scheduler...")
    try:
        scheduler.start()
        print("Started resource scheduler...")
    except (KeyboardInterrupt, SystemExit):
        pass
    print("Stopped resource scheduler...")