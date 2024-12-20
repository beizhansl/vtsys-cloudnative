import logging
import os
from typing import Dict
import requests
from urllib.parse import urlencode, quote
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
import structlog

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S%z'
)
logger = structlog.wrap_logger(logging.getLogger())
prometheusHost = os.getenv("PROMETHEUS_HOST", "localhost")
prometheusPort = os.getenv("PROMETHEUS_PORT", "9090")
prometheusUrl = f"http://{prometheusHost}:{prometheusPort}"
namespace = os.getenv("NAMESPACE", "vtscan")

def handle_retry_error(retry_state):
    logger.error(f"All retries failed with exception: {retry_state.outcome.exception()}")

"""Prometheus response
    Return:
    {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
            {
                "metric": {
                "node": "node1"
                },
                "value": [1672381200, "0.75"]
            },
            {
                "metric": {
                "node": "node2"
                },
                "value": [1672381200, "0.68"]
            }
            // 更多节点...
            ]
        }
    }
"""
@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(1),
    retry=(retry_if_exception_type(requests.exceptions.Timeout) | retry_if_exception_type(requests.exceptions.ConnectionError)),
    retry_error_callback=handle_retry_error
)
def query_prometheus(query: str):
    # 构建查询参数
    params = {
        'query': query
    }
    # 编码查询参数，确保URL安全
    encoded_params = urlencode(params, quote_via=quote)
    # 完整的API URL
    api_url = f'{prometheusUrl}/api/v1/query?{encoded_params}'
    # 发送GET请求到Prometheus API
    response = requests.get(api_url)
    response.raise_for_status()
    
    data = response.json()
    # 检查API调用是否成功
    if data['status'] != 'success' or "data" not in data:
        raise Exception(f"Prometeues query failed: {data.get('error', 'Unknown error')}")
    return data['data']

def query_nodes_cpu_avaliable() -> Dict[str, float]:
    # 查询node整体的idle
    query = 'sum by (node) (rate(node_cpu_seconds_total{mode="idle"}[1m]))'
    # 初始化结果字典
    cpu_available_cores_dict = {}
    try:
        data = query_prometheus(query)
    except Exception as e:
        logger.error(f"Prometeues node available cpu query failed: {e}")
        raise
    # 解析查询结果
    for result in data['result']:
        node_name = result['metric'].get('node', 'unknown')
        available_cores = float(result['value'][1])  # 将字符串转换为浮点数
        cpu_available_cores_dict[node_name] = available_cores
    return cpu_available_cores_dict

def query_namespace_cpu_used():
    # 查询namespace=vtscan的usage时间
    query = f'sum by (instance) (rate(container_cpu_usage_seconds_total{{namespace="{namespace}"}}[1m]))'
    cpu_used_dict = {}
    try:
        data = query_prometheus(query)
    except Exception as e:
        logger.error(f"Prometeues namespace used cpu query failed: {e}") 
        raise
    for result in data['data']['result']:
        node_name = result['metric'].get('instance', 'unknown')
        used_rate = float(result['value'][1])  # 将字符串转换为浮点数
        cpu_used_dict[node_name] = used_rate
    return cpu_used_dict

def query_namespace_memory_used():
    # 查询namespace=vtscan的memory使用
    query = f'sum by (instance) (container_memory_rss{{namespace="{namespace}"}})'
    memory_used_dict = {}
    try:
        data = query_prometheus(query)
    except Exception as e:
        logger.error(f"Prometeues namespace available memory query failed: {e}") 
        raise
    for result in data['data']['result']:
        node_name = result['metric'].get('instance', 'unknown')
        used = float(result['value'][1])  # 将字符串转换为浮点数
        memory_used_dict[node_name] = used
    return memory_used_dict

def query_nodes_memory_available():
    # 查询namespace=vtscan的memory使用
    query = f'node_memory_MemAvailable_bytes'
    memory_available_dict = {}
    try:
        data = query_prometheus(query)
    except Exception as e:
        logger.error(f"Prometeues namespace used memory query failed: {e}") 
        raise
    for result in data['data']['result']:
        node_name = result['metric'].get('node', 'unknown')
        available_memory = float(result['value'][1])  # 将字符串转换为浮点数
        memory_available_dict[node_name] = available_memory
    return memory_available_dict

def nodes_cpu_vt_scan_assignable():
    # 查询node整体的idle时间
    cpu_node_avaliable_dict = query_nodes_cpu_avaliable()
    # 查询namespace=vtscan的非idle时间
    cpu_namespace_used_dict = query_namespace_cpu_used()
    cpu_assignable = {}
    for node in cpu_node_avaliable_dict:
        if node not in cpu_namespace_used_dict:
            continue
        cpu_assignable[node] = cpu_namespace_used_dict[node] + cpu_node_avaliable_dict[node]
    return cpu_assignable

def nodes_memory_vt_scan_assignable():
    # 查询node整体available memory
    memory_node_available_dict = query_nodes_memory_available()
    # 查询namespace=vtscan的非idle时间
    memory_namespace_used_dict = query_namespace_memory_used()
    memory_assignable = {}
    for node in memory_node_available_dict:
        if node not in memory_namespace_used_dict:
            continue
        memory_assignable[node] = memory_namespace_used_dict[node] + memory_node_available_dict[node]
    return memory_assignable
