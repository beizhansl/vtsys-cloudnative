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
    """获取scanners信息
    
    Return: [Scanner.Vtscanner]
    """
    
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
def fetch_scaler_info() -> Dict[str, Tuple[str, float, float, float, float, float, str, str]]:
    """获取autoscaler注册信息,即表明哪些类型扫描器可以被自动扩缩容
    
    Return:
    {
        'openvas': ('HPA|VPA', 30, 300, num, num, num, hostname, port)
        'zap': ('HPA', 20, 500, num, num, num, hostname, port)
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
        scaler_hostname = labels['hostname']
        scaler_port = labels['port']
        scalers_info[engine] = (typeL, cpu_cost, memory_cost, time_cost, external_cpu_cost, 
                                external_memory_cost, scaler_hostname, scaler_port)
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
    """调用某个scanner的缩容接口
    
    Return:
    {
        'ok': True,
        'errmsg': "msg"
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

@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(1),
    retry=(retry_if_exception_type(requests.exceptions.Timeout) | retry_if_exception_type(requests.exceptions.ConnectionError)),
    retry_error_callback=handle_retry_error
)
def call_scaler_scale_out(scaler_url:str, node: str):
    """调用某个scaler的HPA扩容接口
    
    Return:
    {
        'ok': True,
        'errmsg': "msg"
    }
    """
    response = requests.get(
        scaler_url + '/scale_out_with_node',
        params={'node_name': node},
    )
    response.raise_for_status()
    data = response.json()
    ok = data['ok']
    if not ok:
        logger.error(f"Scale {scaler_url} scale out error: {data['errmsg']}")
    return ok

def scale_in_when_task_load_low(engine_load: Dict[str, int], 
                                scanners: List[Scanner.VtScanner],
                                node_usage: List[str, float],
                                scalers: Dict[str, Tuple[str, float, float, float, float, float, str, str]],
                                db_session: Session):
    """对任务负载低的扫描器缩容
    
    Keyword arguments:
    engine_load: 通过engine获取该engine上的任务负载数量
    scanners: 扫描器列表
    node_usage: 节点的负载情况
    scalers: 通过node_name获取node的详细情况('hpa', 'cpu_cost', 'memory_cost', 'time_cost', 'external_cpu_cost', 'external_memory_cost', 'external_memory_cost', 'hostname', 'port')
    db_session: 数据库连接
    """
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

def compute_assign_rate(engine_load: Dict[str,int],
                        scanners: List[Scanner.VtScanner],
                        scalers: Dict[str, Tuple[str, float, float, float, float, float, str, str]], # hpa/vpa, cpu_cost, memory_cost, time_cost, external_cpu_cost, external_memory_cost
                        metric: str
                        ) -> List[Tuple[float, str]]:
    """计算各个engine 已分配比例/应分配比例
    
    Keyword arguments:
    metric: 不同的计算指标: cpu/memory
    scanners: 扫描器列表
    scalers: 通过node_name获取node的详细情况('hpa', 'cpu_cost', 'memory_cost', 'time_cost', 'external_cpu_cost', 'external_memory_cost', 'external_memory_cost', 'hostname', 'port')
    engine_load: 通过engine获取该engine上的任务负载数量
    Return: 
    assign_rate_list: [(1, 'openvas), (1, 'zap')]
    """
    # 计算by engine的已分配数，即parallel值
    engine_assigned:Dict[str, int] = {}
    for scanner in scanners:
        engine = scanner.engine
        if engine not in engine_assigned:
            engine_assigned[engine] = scanner.max_concurrency
        else:
            engine_assigned[engine] += scanner.max_concurrency
    assign_rate_list: List[Tuple[float, str]] = []
    cost_index = 1 if metric == 'cpu' else 2
    external_cost = 3 if metric == 'cpu' else 4
    # 计算应分配的值
    total_expected_assign = .0
    expected_assign_rate:Dict[str, float] = {}
    for engine in scalers:
        total_expected_assign += engine_load[engine] * scalers[engine][cost_index] * scalers[engine][3] + scalers[engine][external_cost]
    # 计算各个engine应该分配的比例
    for engine in scalers:
        expected_assign_rate[engine] = float(engine_load[engine] * scalers[engine][cost_index] * scalers[engine][3] + scalers[engine][external_cost]) / total_expected_assign
    # 计算总共已分配的值
    total_assigned = .0
    for engine in scalers:
        total_assigned += engine_assigned[engine] * scalers[engine][cost_index] * scalers[engine][3] + scalers[engine][external_cost]
    # 计算各个engine已经分配的比例
    assigned_rate:Dict[str, float] = {}
    for engine in scalers:
        assigned_rate[engine] = float(engine_assigned[engine] * scalers[engine][cost_index] * scalers[engine][3] + scalers[engine][external_cost]) / total_assigned
    for engine in scalers:
        assign_rate_list.append((assigned_rate[engine] / expected_assign_rate[engine], engine))
    return assign_rate_list

def compute_usage(other: float,
                  scanner_dict: Dict[int, Scanner.VtScanner],
                  node_scanner_dict: Dict[str, List[int]],
                  metric: str,
                  scalers: Dict[str, Tuple[str, float, float, float, float, float, str, str]]):
    """计算某指标的期望使用值
    
    Keyword arguments:
    other: 除了scanner使用外的负载情况
    scanner_dict: 通过scanner_id获取Vtscanner
    node_scanner_dict: 通过engine获取某node上全部该类型的scanner
    metric: 指标, cpu/memory
    scalers: 通过node_name获取node的详细情况('hpa', 'cpu_cost', 'memory_cost', 'time_cost', 'external_cpu_cost', 'external_memory_cost', 'external_memory_cost', 'hostname', 'port')
    """
    
    expected_usage: float = other
    for engine in node_scanner_dict:
        scanner_list = node_scanner_dict[engine]
        external_cost = scalers[engine][4] if metric == 'cpu' else scalers[engine][5]
        cost = scalers[engine][1] if metric == 'cpu' else scalers[engine][2]
        expected_usage += external_cost
        for scanner_id in scanner_list:
            scanner = scanner_dict[scanner_id]
            expected_usage += cost * scanner.max_concurrency
    return expected_usage

def scale_in_with_metric(metric:str, total: float, other: float, hwl: float, lwl: float,
                         engine_load: Dict[str, int], 
                         scanner_dict: Dict[int, Scanner.VtScanner], 
                         scanners: List[Scanner.VtScanner],
                         node_scanner_dict: Dict[str, List[int]], 
                         scalers:Dict[str, Tuple[str, float, float, float, float, float, str, str]], 
                         db_session: Session) -> bool:
    """根据某指标判断是否需要缩容
    
    Keyword arguments:
    metric: 指标, cpu/memory
    total: node上该指标的总量
    other: 除了scanner使用外的负载情况
    hwl: 高水位线
    lwl: 低水位线
    scanner_dict: 通过scanner_id获取Vtscanner
    node_scanner_dict: 通过engine获取某node上全部该类型的scanner
    scalers: 通过node_name获取node的详细情况('hpa', 'cpu_cost', 'memory_cost', 'time_cost', 'external_cpu_cost', 'external_memory_cost', 'external_memory_cost', 'hostname', 'port')
    db_session: 数据库连接
    """
    expected_usage = compute_usage(other=other, scanner_dict=scanner_dict, node_scanner_dict=node_scanner_dict,
                                           metric=metric, scalers=scalers)
    has_scale_in = False
    # 如果超出高水位则需要缩容, 否则不需要
    if expected_usage < total * hwl:
        return has_scale_in
    # 缩容到什么程度呢？
    # 缩容到hwl和lwl的中间向下
    while expected_usage > total * (hwl + lwl) / 2:
        has_scale_in = True
        # 对这个node上的所有scanner按照总的已分配/应分配进行排序
        # 排序后对第一个node上有的engine的scanner进行缩容，缩容到未高出水位或不再有scanner
        assign_rate_list: List[Tuple[float, str]] = compute_assign_rate(engine_load=engine_load, scanners=scanners,
                                                    scalers=scalers, metric=metric)
        assign_rate_list.sort(key=itemgetter(0) ,reverse=True)
        scale_in_no_scanner = False
        for assign_rate in assign_rate_list:
            engine = assign_rate[1]
            scale_in_fin = False
            if engine in node_scanner_dict:
                for i in range(len(node_scanner_dict[engine])-1, -1, -1): # 存在删除操作所以从后向前遍历
                    scanner_id = node_scanner_dict[engine][i]
                    scanner = scanner_dict[scanner_id]
                    if scanner.max_concurrency == 0:
                        scanner.status = Scanner.Status.WAITING
                        db_session.add(scanner)
                        node_scanner_dict[engine].remove(scanner_id)
                        continue
                    else:  # 进行缩容
                        scale_in_no_scanner = True
                        scanner_url = f"http://{scanner.ipaddr}:{scanner.port}"
                        success = call_scanner_scale_in(scanner_url=scanner_url, num=1)
                        if not success:
                            # 缩容失败去缩容别的
                            node_scanner_dict[engine].remove(scanner_id)
                        else: #缩容成功则退出
                            scanner.max_concurrency -= 1
                            if scanner.max_concurrency == 0:
                                scanner.status = Scanner.Status.WAITING
                                db_session.add(scanner)
                                node_scanner_dict[engine].remove(scanner_id)
                            scale_in_fin = True
                            break
            if scale_in_fin:
                break 
        # 如果没有scanner可以缩容, 则直接结束
        if not scale_in_no_scanner:
            break
        # 再次计算 cpu_expected_usage 
        expected_usage = compute_usage(other=other, scanner_dict=scanner_dict, node_scanner_dict=node_scanner_dict,
                                        metric='cpu', scalers=scalers)
        db_session.flush()
        return has_scale_in

def scale_out_with_cpu_and_memory(node: str,
                                  cpu_total: float, memory_total: float,
                                  cpu_other: float, memory_other: float, 
                                  cpuLwl: float, cpuHwl:float,
                                  memoryLwl: float, memoryHwl: float,
                                  engine_load: Dict[str, int], 
                                  scanner_dict: Dict[int, Scanner.VtScanner], 
                                  scanners: List[Scanner.VtScanner],
                                  node_scanner_dict: Dict[str, List[int]], 
                                  scalers:Dict[str, Tuple[str, float, float, float, float, float, str, str]], 
                                  db_session: Session) -> bool:
    """根据某指标判断是否需要扩容
    
    Keyword arguments:
    metric: 指标, cpu/memory
    total: node上该指标的总量
    other: 除了scanner使用外的负载情况
    lwl: 低水位线
    hwl: 高水位线
    engine_load: 根据engine获取该engine的任务负载数量
    scanners: 扫描器列表
    scanner_dict: 通过scanner_id获取Vtscanner
    node_scanner_dict: 通过engine获取某node上全部该类型的scanner
    scalers: 通过node_name获取node的详细情况('hpa', 'cpu_cost', 'memory_cost', 'time_cost', 'external_cpu_cost', 'external_memory_cost', 'hostname', 'port')
    db_session: 数据库连接
    """
    cpu_expected_usage = compute_usage(other=cpu_other, scanner_dict=scanner_dict, node_scanner_dict=node_scanner_dict,
                                           metric='cpu', scalers=scalers)
    memory_expected_usage = compute_usage(other=memory_other, scanner_dict=scanner_dict, node_scanner_dict=node_scanner_dict,
                                           metric='memory', scalers=scalers)
    # 如果低于高水位则需要扩容, 否则不需要
    if cpu_expected_usage > cpu_total * cpuLwl\
        or memory_expected_usage > memory_total * memoryLwl:
        return
    cpu_can_apply_line = cpu_total * ((cpuLwl + cpuHwl) / 2 + cpuHwl) / 2
    memory_can_apply_line = memory_total * ((memoryLwl + memoryHwl) / 2 + memoryHwl) / 2
    while cpu_expected_usage < cpu_can_apply_line and memory_expected_usage < memory_can_apply_line:
        # 对这个node上的所有scanner按照总的已分配/应分配进行排序
        # 排序后对第一个node上有的engine的scanner进行扩容，扩容到中间或不再有scanner
        assign_rate_list: List[Tuple[float, str]] = compute_assign_rate(engine_load=engine_load, scanners=scanners,
                                                    scalers=scalers, metric='cpu')
        assign_rate_list.sort(key=itemgetter(0))
        scale_out_no_scanner = False
        for assign_rate in assign_rate_list:
            engine = assign_rate[1]
            scale_out_fin = False
            scale_type = scalers[engine][0]
            # 既没有vpa标识也没有hpa表示, 直接忽略不进行扩容
            if 'vpa' not in scale_type and 'hpa' not in scale_type:
                continue
            # 该engine扩充一个任务是否会直接超过
            cpu_cost = scalers[engine][1] 
            memory_cost = scalers[engine][2]
            cpu_after_scale_usage = cpu_expected_usage + cpu_cost
            memory_after_scale_uasge = memory_expected_usage + memory_cost
            # 仅支持hpa的话需要进行pod的启动需要把external的加上
            if 'vpa' not in scale_type:
                cpu_after_scale_usage += scalers[engine][4] 
                memory_after_scale_uasge += scalers[engine][5]
            if cpu_after_scale_usage > cpu_can_apply_line \
                or memory_after_scale_uasge > memory_can_apply_line:
                continue
            # 未超过则扩展
            # 按照engine支持的扩展方式进行
            #     如果支持vpc, 直接增加并发度
            #     如果不支持, 则启动新的pod
            can_hpa = True
            if 'vpa' in scale_type:
                scanner_list = node_scanner_dict[engine]
                # 扫描器数量为0则需要先通过hpa启动扫描器
                if len(scanner_list) > 0:
                    can_hpa = False
                    waiting_scale_scanner = []
                    for scanner_id in scanner_list:
                        scanner_parallel = scanner_dict[scanner_id].max_concurrency
                        waiting_scale_scanner.append((scanner_parallel, scanner_id))
                    # 选择并发度最小的扩充
                    waiting_scale_scanner.sort(key=itemgetter(0))
                    scanner_id = waiting_scale_scanner[0][1]
                    scanner = scanner_dict[scanner_id]
                    scanner.max_concurrency += 1
                    db_session.add(scanner)
                    scale_out_fin = True
                    scale_out_no_scanner = True
            # 不能进行vpa或者没有scanner可以vpa则进行hpa
            if 'hpa' in scale_type and can_hpa:
                scaler_hostname = scalers[engine][6] 
                scaler_port = scalers[engine][7]
                scaler_url = f"http://{scaler_hostname}:{scaler_port}"
                success = call_scaler_scale_out(scaler_url=scaler_url, node=node)
                if success:
                    scale_out_fin = True
                    scale_out_no_scanner = True
            if scale_out_fin:
                break 
        # 如果没有scanner可以扩容, 则直接结束
        if not scale_out_no_scanner:
            break
        # 再次计算 cpu_expected_usage, memory_expected_uasge
        cpu_expected_usage = compute_usage(other=cpu_other, scanner_dict=scanner_dict, node_scanner_dict=node_scanner_dict,
                                        metric='cpu', scalers=scalers)
        memory_expected_usage = compute_usage(other=memory_other, scanner_dict=scanner_dict, node_scanner_dict=node_scanner_dict,
                                        metric='memory', scalers=scalers)
        db_session.flush()
        return

def scale_in_or_out_with_node_load(node_cpu_used: Dict[str, float],
                                 node_cpu_available: Dict[str, float],
                                 node_memory_used: Dict[str, float],
                                 node_memory_available: Dict[str, float],
                                 node_info: Dict[str, Tuple[float, float]],
                                 scalers: Dict[str, Tuple[str, float, float, float, float, float, str, str]],
                                 scanners: List[Scanner.VtScanner],
                                 engine_load: Dict[str, int],
                                 db_session: Session):
    """根据指标判断是否需要缩容或扩容, by-node
    
    Keyword arguments:
    node_cpu_used: 通过node_name获取所有扫描器在节点上的cpu使用量
    node_cpu_available: 通过node_name获取节点上的cpu空闲量
    node_memory_used: 通过node_name获取所有扫描器在节点上的memory使用量
    node_memory_available: 通过node_name获取节点上的memory空闲量
    node_info: 通过node_name获取节点的总量信息,('cpu_total' 'memory_total')
    scalers: 通过node_name获取node的详细情况('hpa', 'cpu_cost', 'memory_cost', 'time_cost', 'external_cpu_cost', 'external_memory_cost')
    scanners: scanner列表
    engine_load: 通过engine获取该engine上的任务负载数量
    db_session: 数据库连接
    """
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
        memory_total = node_info[node][1]
        memory_other = memory_total - node_memory_available[node] - node_memory_used[node]
        scanner_dict:Dict[int, Scanner.VtScanner] = {}
        node_scanner_dict: Dict[str, List[int]] = {}
        for scanner in scanners:
            if scanner.engine not in scalers or scanner.node != node:
                continue
            scanner_dict[scanner.id] = scanner
            if scanner.status != Scanner.Status.ENABLE:
                continue
            engine = scanner.engine
            if engine not in node_scanner_dict:
                node_scanner_dict[engine] = [scanner.id]
            else:
                node_scanner_dict[engine].append(scanner.id)
        # 判断并进行CPU指标的缩容
        has_cpu_scale_in = scale_in_with_metric(metric='cpu', total=cpu_total, other=cpu_other, hwl=cpuHwl,
                             engine_load=engine_load, scanner_dict=scanner_dict, scanners=scanners,
                             node_scanner_dict=node_scanner_dict, scalers=scalers,
                             db_session=db_session)
        has_memory_scale_in = scale_in_with_metric(metric='memory', total=memory_total, other=memory_other, hwl=memoryHwl,
                             engine_load=engine_load, scanner_dict=scanner_dict, scanners=scanners,
                             node_scanner_dict=node_scanner_dict, scalers=scalers,
                             db_session=db_session)
        # 进行过缩容则不需要再扩容了
        if has_cpu_scale_in or has_memory_scale_in:
            continue
        # 判断并进行Memory指标的扩容
        scale_out_with_cpu_and_memory(node=node, cpu_total=cpu_total, cpu_other=cpu_other, memory_total=memory_total,
                                      memory_other=memory_other, cpuLwl=cpuLwl, cpuHwl=cpuHwl, memoryLwl=memoryLwl,
                                      memoryHwl=memoryHwl, engine_load=engine_load, scanner_dict=scanner_dict, scanners=scanners,
                                      node_scanner_dict=node_scanner_dict, scalers=scalers,
                                      db_session=db_session)
        db_session.flush()

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
                node_cpu_usage[node] = 1- node_cpu_available[node]/node_total
            for node in node_memory_available:
                node_total = node_info[node][0]
                node_memory_usage[node] = 1- node_memory_available[node]/node_total
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
                                         node_info=node_info, scalers=scalers, scanners=scanners, engine_load=engine_load,
                                         db_session=db_session)
            # 3. 全局再平衡

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
