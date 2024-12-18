from typing import Dict, List
from apscheduler.schedulers.blocking import BlockingScheduler
import logging
import structlog
from datetime import datetime
from ..model import scanner as Scanner
import os
from ..tidb_sql import get_db_session
import requests
from sqlalchemy import Enum
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
# from kubernetes import client as k8s_client
from ..k8s_client import load_kube_config
from kubernetes import client
from kubernetes.client import V1PodList
from kubernetes.client.rest import ApiException
from datetime import timezone

# 设置结构化日志
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S%z'
)
logger = structlog.wrap_logger(logging.getLogger())
# 获取资源管理器的地址
taskManagerHost = os.getenv("TASK_MANAGER_HOST", "localhost")
taskManagerPort = os.getenv("TASK_MANAGER_PORT", "4000")
taskManagerUrl = f"http://{taskManagerHost}:{taskManagerPort}"
deleteWaitTime = os.getenv("DELETE_WAIT_TIME", "600")
namespace = os.getenv("NAMESPACE", "vtscan")

def handle_retry_error(retry_state):
    logger.error(f"All retries failed with exception: {retry_state.outcome.exception()}")

class K8sPodStatus(Enum):
    PENDING = 'Pending'
    RUNNING = 'Running'
    SUCCEEDED = 'Succeeded'
    FAILED = 'Failed'
    UNKNOWN = 'Unknown'

def get_db_scanners(db_session: Session):
    query = (
        db_session.query(Scanner.VtScanner)
        .filter(Scanner.VtScanner.status.in_(
            [Scanner.Status.DISABLE, Scanner.Status.ENABLE, Scanner.Status.WAITING, Scanner.Status.DELETING]
        ))
    )
    return query.all()

def fetch_scanners():
    v1 = client.CoreV1Api()
    # 首先获取所有负责scale的scanner的scaler
    scanners = []
    try:
        label_selector = "type=scanner,group=vtscan"
        pods:V1PodList = v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector, watch=False)
        for pod in pods.items:
            scanners.append({
                'name': pod.metadata.name,
                'labels': pod.metadata.labels,
                'status': pod.status.phase,
                'ipaddr': pod.status.pod_ip,
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
        pods:V1PodList = v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector, watch=False)
        for pod in pods.items:
            scanner_scalers.append({
                'name': pod.metadata.name,
                'labels': pod.metadata.labels,
                'status': pod.status.phase
            })
    except ApiException as e:
        logger.error(f"Exception when calling CoreV1Api->list_pod_for_all_namespaces: {e}\n")
    return scanner_scalers

def list_trans_to_dict(scanners: list):
    scanner_dict = {}
    for scanner in scanners:
        scanner_dict[scanner['name']] = scanner
    return scanner_dict

def log_delete_scanner_succ(scanner_name: str):
    logger.info(f"scanner {scanner_name} delete successfully")

def log_delete_scanner_wrong(scanner_name: str):
    logger.error(f"scanner {scanner_name} delete Unexpected")

# query scanner task from task manager
@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(1),
    retry=(retry_if_exception_type(requests.exceptions.Timeout) | retry_if_exception_type(requests.exceptions.ConnectionError)),
    retry_error_callback=handle_retry_error
)
def check_scanner_running_task(scanner_name: str):
    """
        reponse:
        {
            running_task_num: 运行中任务数量
        }
    """
    response = requests.get(
        taskManagerUrl + '/get_running_task_num',
        params={'scanner_name': scanner_name},
    )
    response.raise_for_status()
    data = response.json()
    running_task_num = data['running_task_num']
    if running_task_num > 0:
        return False
    return True

def calculate_wait_time(record_time):
    current_time = datetime.now(timezone.utc)
    wait_time = current_time - record_time
    return int(wait_time.total_seconds())

def delete_deleting_scanner(scanner_name:str):
    v1 = client.CoreV1Api()
    try:
        # 删除Pod
        api_response = v1.delete_namespaced_pod(
            name=scanner_name,
            namespace=namespace,
            # This body is required for the Delete operation
            # It specifies the propagation policy to use (Foreground, Background, Orphan)
            body=client.V1DeleteOptions(
                grace_period_seconds=0
            )
        )
        logger.info("Pod deleting. status='%s'" % str(api_response.status))
    except client.ApiException as e:
        logger.error("Exception when calling CoreV1Api->delete_namespaced_pod: %s\n" % e)

def trans_db_scanner_status(db_scanner:Scanner.VtScanner, k8s_scanner_dict: Dict[dict]):
    if db_scanner.name not in k8s_scanner_dict:
        if db_scanner.status != Scanner.Status.DELETING:
            log_delete_scanner_wrong(db_scanner.name)
        else:
            log_delete_scanner_succ(db_scanner.name)
        db_scanner.status = Scanner.Status.DELETED
        return
    k8s_scanner = k8s_scanner_dict[db_scanner.name]
    k8s_scanner_labels = k8s_scanner['labels']
    k8s_scanner_engine = k8s_scanner_labels['engine']
    k8s_scanner_port = k8s_scanner_labels.get('port', '80')
    k8s_scanner_filetype = k8s_scanner_labels.get('filetype', Scanner.FileType.HTML)
    if k8s_scanner['ipaddr'] != db_scanner.ipaddr or \
        k8s_scanner_engine != db_scanner.engine or \
        k8s_scanner_port != db_scanner.port or \
        k8s_scanner_filetype != db_scanner.filetype:
        logger.error(f"scanner {db_scanner.name} ip inconsistent, deleting")
        db_scanner.status == Scanner.Status.DELETING
        return
    # 删除的话一定是什么都没了
    if k8s_scanner['status'] in [K8sPodStatus.FAILED, K8sPodStatus.SUCCEEDED]:
        if db_scanner.status != Scanner.Status.DELETING:
            log_delete_scanner_wrong(db_scanner.name)
        db_scanner.status = Scanner.Status.DELETING
    if k8s_scanner['status'] in [K8sPodStatus.PENDING]:
        if db_scanner.status != Scanner.Status.DISABLE:
            logger.error(f"scanner {db_scanner.name} trans to Pending unexpected, deleting")
            db_scanner.status = Scanner.Status.DELETING
    if k8s_scanner['status'] in [K8sPodStatus.RUNNING]:
        if db_scanner.status == Scanner.Status.DISABLE:
            logger.info(f"scanner {db_scanner.name} trans to Running successfully")
            db_scanner.status = Scanner.Status.ENABLE
        # if db_scanner.status == Scanner.Status.DELETED:
        #     logger.error(f"scanner {db_scanner.name} trans to Running unexpected, deleting")
        #     db_scanner.status = Scanner.Status.DELETING
    # 对于unknown报错不处理
    if k8s_scanner['status'] in [K8sPodStatus.UNKNOWN]:
        logger.error(f"scanner {db_scanner.name} in unknown status")
    # 处理处于等待状态的scanner
    #   未超时
    #   超时任务未处理完毕
    #   超时任务处理完毕
    if db_scanner.status == Scanner.Status.WAITING:
        wait_time = calculate_wait_time(db_scanner.update_time)
        if wait_time < deleteWaitTime:
            return
        try:
            canDelete = check_scanner_running_task(db_scanner.name)
        except Exception as e:
            logger.error(f"check scanner running task error: {e}")
        if not canDelete:
            return
        db_scanner.status = Scanner.Status.DELETING
    # 处理异常scanner, 直接删除
    if db_scanner.except_num >= db_scanner.max_concurrency:
        db_scanner.status = Scanner.Status.DELETING
    # 对于deleting状态下的scanner执行删除操作
    if db_scanner.status == Scanner.Status.DELETED:
        delete_deleting_scanner(db_scanner.name)    

def insert_scanners(k8s_scanenrs: List[dict], db_scanner_dict: Dict[str, Scanner.VtScanner]):
    new_scanners = []
    for k8s_scanner in k8s_scanenrs:
        k8s_scanner_name = k8s_scanner['name']
        if k8s_scanner_name not in db_scanner_dict:
            k8s_scanner_status = k8s_scanner['status']
            if k8s_scanner_status != K8sPodStatus.RUNNING:
                continue
            k8s_scanner_labels = k8s_scanner['labels']
            k8s_scanner_ipaddr = k8s_scanner['ipaddr']
            new_scanner = Scanner.VtScanner(
                name=k8s_scanner_name,
                type=k8s_scanner_labels['scan_type'],
                engine=k8s_scanner_labels['engine'],
                ipaddr=k8s_scanner_ipaddr,
                port=k8s_scanner_labels.get('port', '80'),
                filetype=k8s_scanner_labels.get('filetype', Scanner.FileType.HTML),
                max_concurrency=k8s_scanner_labels['max_concurrency']
            )
            new_scanners.append(new_scanner)
    return new_scanners

def trace_scanners():
    logger.info("Tracing tasks")
    try:
        with get_db_session() as db_session:
            # 获取数据库中运行中（enable/disable）的扫描器
            db_scanners = get_db_scanners()
            # 从k8s获取所有运行中scanner
            succ, k8s_scanners = fetch_scanners()
            if not succ:
                return
            db_scanner_dict = list_trans_to_dict(db_scanners)
            k8s_scanner_dict = list_trans_to_dict(k8s_scanners)
            # 检查db_scanner
            for db_scanner in db_scanners:
                # 不在就是已经删除了，直接删除
                trans_db_scanner_status(db_scanner, k8s_scanner_dict)
            # 插入新加入的scanner
            new_scanners = insert_scanners(k8s_scanners, db_scanner_dict)
            # 全部scanner变更写入数据库
            db_session.add_all(db_scanners)
            db_session.add_all(new_scanners)
    except Exception as e:
        logger.error(f"Dbsession save {db_session} exception: {e}")

# sacnner的扩缩容交给各个scanner自己实现的扩缩器处理
# 资源管理器向他们提供集群资源信息, 由这些扩缩器决定是否进行扩缩，以及如何扩缩
# def autoscale_scanners():
#     autoscalers = fetch_scanner_scalers()
#     # 对每个autoscaler进行处理
#     if len(autoscale_scanners) == 0:
#         return

def resource_schedule():
    # 周期性执行任务逻辑
    # 检查扫描器表
    # 1. 扩缩容  - 交给各个扩缩器自己处理
    #   1.1. 扩容，VPA/HPA
    #   1.2. 缩容，VPA/HPA，enable->disable->deleted
    #                                     ->enable ?
    # 2. 追踪扫描器
    #   2.1. 对比kubernetes正在运行中的和数据库中的扫描器
    #   2.2. 进行健康检测，将标记为非健康状态的扫描器下线
    logger.info("Executing the resource periodic task")
    trace_scanners()

if __name__ == "__main__":
    # 首先自动加载配置
    try:
        load_kube_config()
        logger.info("Loaded k8s configuration.")
    except Exception as e:
        logger.error((e))
        raise
    scheduler = BlockingScheduler()
    scheduler.add_job(resource_schedule, 'interval', seconds=60)  # 每60秒执行一次
    logger.info("Starting resource scheduler...")
    try:
        scheduler.start()
        logger.info("Started resource scheduler...")
    except (KeyboardInterrupt, SystemExit):
        pass
    logger.info("Stopped resource scheduler...")
