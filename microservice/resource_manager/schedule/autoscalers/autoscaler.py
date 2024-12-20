from typing import Dict, List
from apscheduler.schedulers.blocking import BlockingScheduler
import logging
import structlog
from datetime import datetime
from resource_manager.model import scanner as Scanner
import os
from resource_manager.tidb_sql import get_db_session
import requests
from sqlalchemy import Enum
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
# from kubernetes import client as k8s_client
from resource_manager.k8s_client import load_kube_config
from kubernetes import client
from kubernetes.client import V1PodList
from kubernetes.client.rest import ApiException
from datetime import timezone
from resource_manager.promql import nodes_cpu_vt_scan_assignable, nodes_memory_vt_scan_assignable 

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
resourceManagerHost = os.getenv("RESOURCE_MANAGER_HOST", "localhost")
resourceManagerPort = os.getenv("RESOURCE_MANAGER_PORT", "4000")
resourceManagerUrl = f"http://{resourceManagerHost}:{resourceManagerPort}"
scannerNamespace = os.getenv("SCANNER_NAMESPACE", "vt-scanner")

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

@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(1),
    retry=(retry_if_exception_type(requests.exceptions.Timeout) | retry_if_exception_type(requests.exceptions.ConnectionError)),
    retry_error_callback=handle_retry_error
)
def fetch_node_info():
    """获取节点信息
    
    Return: 
    {
        "node1": (cpu_available, memory_available)
    }
    """
    v1 = client.CoreV1Api()
    # 获取所有节点的信息
    nodes = v1.list_node().items
    node_info = {}
    for node in nodes:
        total_cpu = node.status.allocatable['cpu']
        total_memory = node.status.allocatable['memory']
        node_name = node.metadata.name
        node_info[node_name] = (total_cpu, total_memory) 
    return node_info

@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(1),
    retry=(retry_if_exception_type(requests.exceptions.Timeout) | retry_if_exception_type(requests.exceptions.ConnectionError)),
    retry_error_callback=handle_retry_error
)
def fetch_pod_info():
    """获取openvas扫描器pod信息"""
    v1 = client.CoreV1Api()
    pods = v1.list_namespaced_pod(namespace=scannerNamespace)
    return pods
    
def trace_nodes_usage():
    try:
        node_info = fetch_node_info()
        cpu_assignable = nodes_cpu_vt_scan_assignable()
        memory_assignable = nodes_memory_vt_scan_assignable()
        pod_info = fetch_pod_info()
        # 先收缩再扩充
        # 在扩容的时候需要知道各种scanner的比例, 按照任务数*执行时间来分配
        
        # 
    except Exception as e:
        logger.error(f"get node info error: {e}")
        return

# 全局唯一自动扩缩容器
def autoscaler():
    # 周期性执行任务逻辑
    # 扩缩容 - 统一处理
    # 从prometheus获取各个节点的相关信息
    # 按照策略确定是否扩容/缩容
    #   1.1. 扩容，VPA/HPA
    #   1.2. 缩容，VPA/HPA，enable->disable->deleted
    logger.info("Executing the resource periodic task")
    trace_nodes_usage()

if __name__ == "__main__":
    # 首先自动加载配置
    try:
        load_kube_config()
        logger.info("Loaded k8s configuration.")
    except Exception as e:
        logger.error((e))
        raise
    scheduler = BlockingScheduler()
    scheduler.add_job(autoscaler, 'interval', seconds=30)  # 每30秒执行一次
    logger.info("Starting autoscaler...")
    try:
        scheduler.start()
        logger.info("Started autoscaler...")
    except (KeyboardInterrupt, SystemExit):
        pass
    logger.info("Stopped autoscaler...")
