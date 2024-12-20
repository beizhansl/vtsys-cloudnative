from typing import Dict, List
from apscheduler.schedulers.blocking import BlockingScheduler
import logging
import structlog
from datetime import datetime
from resource_manager.model import scanner as Scanner
import os
from resource_manager.tidb_sql import get_db_session
import requests
from sqlalchemy import Enum, Tuple
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
# from kubernetes import client as k8s_client
from resource_manager.k8s_client import load_kube_config
from kubernetes import client
from kubernetes.client import V1PodList
from kubernetes.client.rest import ApiException
from datetime import timezone
from resource_manager.promql import query_nodes_cpu_avaliable, query_namespace_cpu_used, query_namespace_memory_used, query_nodes_memory_available 
from operator import itemgetter

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
cpuHwl = float(os.getenv("CPU_HWL", "0.9"))
cpuLwl = float(os.getenv("CPU_LWL", "0.7"))
memoryHwl = float(os.getenv("MEMORY_HWL", "0.9"))
memoryLwl = float(os.getenv("MEMORY_LWL", "0.7"))
cpuWeight = float(os.getenv("CPU_WEIGHT", "0.5"))
memoryWeight = float(os.getenv("MEMORY_WEIGHT", "0.5"))

def handle_retry_error(retry_state):
    logger.error(f"All retries failed with exception: {retry_state.outcome.exception()}")

class K8sPodStatus(Enum):
        PENDING = 'Pending'
        RUNNING = 'Running'
        SUCCEEDED = 'Succeeded'
        FAILED = 'Failed'
        UNKNOWN = 'Unknown'

def get_db_scanners(db_session: Session) -> List[Scanner.VtScanner]:
    query = (
        db_session.query(Scanner.VtScanner)
        .filter(Scanner.VtScanner.status.in_(
            [Scanner.Status.DISABLE, Scanner.Status.ENABLE, Scanner.Status.WAITING]
        ))
    )
    return query.all()

@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(1),
    retry=(retry_if_exception_type(requests.exceptions.Timeout) | retry_if_exception_type(requests.exceptions.ConnectionError)),
    retry_error_callback=handle_retry_error
)
def fetch_node_info() ->Dict[str, Tuple[float, float]]:
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

@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(1),
    retry=(retry_if_exception_type(requests.exceptions.Timeout) | retry_if_exception_type(requests.exceptions.ConnectionError)),
    retry_error_callback=handle_retry_error
)
def fetch_scaler_info() -> Dict[str, Tuple[str, float, float, float, float, float]]:
    """获取autoscaler注册信息,即表明哪些类型扫描器可以被自动扩缩容
    
    Return:
    {
        'openvas': ('HPA|VPA', 30, 300, num, num, num)
        'zap': ('HPA', 20, 500, num, num, num)
    }
    """
    # 创建自定义对象 API 实例
    api_instance = client.CustomObjectsApi()

    # 定义 CRD 的组、版本和复数形式的资源名称
    group = 'cstcloud.cn'
    version = 'v1'  # 版本应与 CRD 中定义的一致
    plural = 'scalerregisters'  # 这应该是你在 CRD 中定义的复数形式
    namespace = ''
    scalers = api_instance.list_namespaced_custom_object(group, version, namespace, plural)
    scalers_info = {}
    for scaler in scalers['items']:
        labels = scaler['metadata'].get('labels', {})
        if 'engine' not in labels or not labels['engine']\
            or 'type' not in labels or not labels['type']:
            continue
        engine = labels['engine']
        typeL = labels['type']
        cpu_cost = float(labels['cpu_cost'])
        memory_cost = float(labels['memory_cost'])
        time_cost = float(labels['time_cost'])
        external_cpu_cost = float(labels['external_cpu_cost'])
        external_memory_cost = float(labels['external_memory_cost'])
        scalers_info[engine] = (typeL, cpu_cost, memory_cost, time_cost, external_cpu_cost, external_memory_cost)
    return scalers_info

# query scanner_engine tasks from task manager
@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(1),
    retry=(retry_if_exception_type(requests.exceptions.Timeout) | retry_if_exception_type(requests.exceptions.ConnectionError)),
    retry_error_callback=handle_retry_error
)
def list_engine_load() -> Dict[str, int]:
    """从任务管理模块获取所有类型的扫描器的任务负载情况
    
    Return:
    {
        'openvas': 100,
        'zap': 30
    }
    """
    response = requests.get(
        taskManagerUrl + '/list_engine_tasks_num',
    )
    response.raise_for_status()
    data = response.json()
    task_count_list = data['task_count']
    scanner_load = {}
    for task_count in task_count_list:
        scanner_type = task_count['scanner_type']
        num = task_count['num']
        scanner_load[scanner_type] = num
    return scanner_load

# query scanner running tasks from task manager
@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(1),
    retry=(retry_if_exception_type(requests.exceptions.Timeout) | retry_if_exception_type(requests.exceptions.ConnectionError)),
    retry_error_callback=handle_retry_error
)
def list_scanenr_running_tasks_num(engines: List[str]) -> Dict[str, int]:
    """从任务管理模块获取所有扫描器的任务正在执行情况
    
    Return:
    {
        '1': 1,
        '2': 3,
        scanner_id: num
    }
    """
    data = {
        "engines": engines
    }
    response = requests.get(
        taskManagerUrl + '/list_running_tasks_num',
        json=data
    )
    response.raise_for_status()
    data = response.json()
    task_count_list = data['task_count']
    scanner_num = {}
    for task_count in task_count_list:
        scanner_type = task_count['scanner_id']
        num = task_count['num']
        scanner_num[scanner_type] = num
    return scanner_num

# call scanner to scale in
@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(1),
    retry=(retry_if_exception_type(requests.exceptions.Timeout) | retry_if_exception_type(requests.exceptions.ConnectionError)),
    retry_error_callback=handle_retry_error
)
def call_scanner_scale_in(scanner_url:str, num: int):
    """从任务管理模块获取所有扫描器的任务正在执行情况
    
    Return:
    {
        '1': 1,
        '2': 3,
        scanner_id: num
    }
    """
    response = requests.get(
        scanner_url + '/scale_in_with_num',
        params={'num': num},
    )
    response.raise_for_status()
    data = response.json()
    ok = data['ok']
    if not ok:
        logger.error(f"Scanner {scanner_url} scale in error: {data['errmsg']}")
    return ok

def scale_in_when_task_load_low(engine_load: Dict[str, int], 
                                scanners: List[Scanner.VtScanner],
                                node_usage: List[str, float],
                                scalers: Dict[str, Tuple[str, int, int, float]],
                                db_session: Session):
    try:
        engine_parallel:Dict[str, int] = {}
        scanner_dict:Dict[int, Scanner.VtScanner] = {}
        for scanner in scanners:
            scanner_dict[scanner.id] = scanner
            engine = scanner.engine
            num = scanner.max_concurrency
            if engine in engine_parallel:
                engine_parallel[engine] += num
            else:
                engine_parallel[engine] = num
        need_scale_in = []
        need_scale_num = {}
        for engine in engine_load:
            if engine not in scalers:
                continue
            if engine_load[engine] < engine_parallel[engine]:
                need_scale_in.append(engine)
                need_scale_num[engine] = engine_parallel[engine] - engine_load[engine]
        # 获取各个scanner运行中的任务数
        scanner_task_num = list_scanenr_running_tasks_num(need_scale_in)
        waiting_scale_in: Dict[str, List[Tuple]] = {}
        for scanner_id in scanner_task_num:
            parallel_num = scanner_dict[scanner_id].max_concurrency
            running_num = scanner_task_num[scanner_id]
            # 小于可以触发缩容, 按照node的负载情况排序, 删除掉总差数
            node_name = scanner_dict[scanner_id].node
            usage = node_usage[node_name]
            engine = scanner_dict[scanner_id].engine
            if parallel_num > running_num:
                if engine in waiting_scale_in:
                    waiting_scale_in[engine].append((usage, parallel_num - running_num, scanner_id))
                else:
                    waiting_scale_in[engine] = [(usage, parallel_num - running_num, scanner_id)]
        # 遍历engine, 进行缩容, by engine
        for engine in waiting_scale_in:
            info_list = waiting_scale_in[engine]
            info_list.sort(key=itemgetter(0,1), reverse=True)
            for info in info_list:
                if need_scale_num[engine] <= 0:
                    break
                scanner_id = info[2]
                scale_num = info[1]
                # ipaddr = scanner_dict[scanner_id].ipaddr
                # port = scanner_dict[scanner_id].port
                # url = f"http://{ipaddr}:{port}"
                # call_scanner_scale_in(url, scale_num)
                need_scale_num[engine] -= scale_num
                # 数据库中的scanner同样缩容
                scanner = scanner_dict[scanner_id]
                scanner.max_concurrency -= scale_num
                # 如果等于0, 则直接进入waiting状态
                if scanner.max_concurrency == 0:
                    scanner.status = Scanner.Status.WAITING
                db_session.add(scanner)
                
    except Exception as e:
        logger.error(f"scale in with task load low error: {e}")

def scale_in_or_out_with_node_load(node_cpu_used: Dict[str, float],
                                 node_cpu_available: Dict[str, float],
                                 node_memory_used: Dict[str, float],
                                 node_memory_available: Dict[str, float],
                                 node_info: Dict[str, Tuple[float, float]],
                                 scalers: Dict[str, Tuple[str, int, int, float, int, int]],
                                 scanners: List[Scanner.VtScanner],
                                 db_session: Session):
    # by node
    for node in node_info:
        # 首先计算node的资源负载情况，判断是否需要缩容
        if node not in node_cpu_available or node not in node_cpu_used:
            logger.error(f"node {node} node_cpu_usage not found")
            continue
        if node not in node_memory_available or node not in node_memory_used:
            logger.error(f"node {node} node_memory_usage not found")
            continue
        # 资源使用率计算
        cpu_total = node_info[node][0]
        cpu_other = cpu_total - node_cpu_available[node] - node_cpu_used[node]
        cpu_expected_usage = cpu_other + scalers[engine][4]
        memory_total = node_info[node][1]
        memory_other = memory_total - node_memory_available[node] - node_memory_used[node]
        memory_expected_usage = memory_other + scalers[engine][5]
        scanner_dict = {}
        for scanner in scanners:
            if scanner.engine not in scalers or scanner.node != node:
                continue
            engine = scanner.engine
            scanner_dict[scanner.id] = scanner
            cpu_cost = scalers[engine][1]
            memory_cost = scalers[engine][2]
            time_cost = scalers[engine][3]
            cpu_expected_usage += cpu_cost * scanner.max_concurrency
            memory_expected_usage += memory_cost * scanner.max_concurrency
        # 如果超出高水位则需要缩容, 否则不需要
        if cpu_expected_usage > cpu_total * cpuHwl \
            or memory_expected_usage > memory_total * memoryHwl:
            pass
        
        # 如果低于低水位则扩容, 否则不需要        
        if cpu_expected_usage < cpu_total * cpuLwl \
            and memory_expected_usage < memory_total * memoryLwl:
            pass                  

# 全局唯一自动扩缩容器
def autoscaler():
    # 周期性执行任务逻辑
    # 扩缩容 - 统一处理
    # 从prometheus获取各个节点的相关信息
    # 按照策略确定是否扩容/缩容
    #   1.1. 扩容，VPA/HPA
    #            I  任务负载高 
    #            II 且资源负载低 by node
    #   1.2. 缩容，VPA/HPA，enable->disable->deleted
    #            I  任务负载低 by scaler
    #            II 或者资源负载高  by node
    logger.info("Executing the autoscale periodic task")
    try:
        with get_db_session() as db_session:
            # 首先获取需要自动扩缩容的扫描器
            scalers = fetch_scaler_info()
            # 所有engine的负载
            engine_load = list_engine_load()
            # 所有未删除的scanner
            scanners = get_db_scanners(db_session=db_session)
            # 所有node的cpu空闲情况
            node_cpu_available = query_nodes_cpu_avaliable()
            # 所有node的memory空闲情况
            node_memory_available = query_nodes_memory_available()
            # 所有node的总体信息
            node_info = fetch_node_info()
            # 1. 首先处理任务负载低时的缩容 by engine
            # 计算所有node的使用率
            node_cpu_usage = {}
            node_memory_usage = {}
            for node in node_cpu_available:
                node_total = node_info[node][0]
                node_cpu_usage[node] = 1- node_total/node_cpu_available[node]
            for node in node_memory_available:
                node_total = node_info[node][0]
                node_memory_usage[node] = 1- node_total/node_memory_available[node]
            node_usage = {}
            for node in node_cpu_usage:
                if node not in node_memory_available:
                    logger.error(f"node {node} memory lost")
                node_usage[node] = node_cpu_usage[node]
                node_usage[node] = cpuWeight * node_cpu_usage[node] + memoryWeight * node_memory_usage[node]
            scale_in_when_task_load_low(engine_load=engine_load, scanners=scanners, 
                                        node_usage=node_usage, scalers=scalers, db_session=db_session)
            db_session.flush()
            # 2. 资源高时缩容 by node
            node_cpu_used = query_namespace_cpu_used()
            node_memory_used = query_namespace_memory_used()
            scale_in_or_out_with_node_load(node_cpu_used=node_cpu_used, node_cpu_available=node_cpu_available,
                                         node_memory_available=node_memory_available, node_memory_used=node_memory_used,
                                         node_info=node_info, scalers=scalers, scanners=scanners, db_session=db_session)

    except Exception as e:
        logger.error(f"Execute the autoscale error: {e}")

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
