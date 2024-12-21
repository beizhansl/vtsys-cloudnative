import yaml
from kubernetes import client, config
from datetime import datetime
from k8s_client import load_kube_config
import random
import string
import logging
import structlog

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S%z'
)
logger = structlog.wrap_logger(logging.getLogger())

def generate_unique_pod_name(base_name='openvas'):
    """Generate a unique pod name based on the given base name."""
    random_string = ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))
    return f"{base_name}-{random_string}"

def check_node_label(node_name: str, label_key='openvas_data', label_value='ready'):
    """
    检查指定节点是否有给定的标签
    
    :param node_name: 节点名称
    :param label_key: 标签键
    :param label_value: 标签值
    :return: 如果存在返回True, 否则返回False
    """
    load_kube_config()
    # 创建CoreV1Api实例
    api_instance = client.CoreV1Api()
    try:
        # 获取指定节点的信息
        node = api_instance.read_node(name=node_name)
        # 检查节点标签
        labels = node.metadata.labels or {}
        if labels.get(label_key) == label_value:
            return True
        else:
            logger.error(f"Node {node_name} does not have the label {label_key}={label_value}.")
            return False
    except client.exceptions.ApiException as e:
        logger.error(f"Exception when calling CoreV1Api->read_node {node_name}: %s\n" % e)
        return False

def create_pod_from_yaml(node_name: str, yaml_path: str="./openvas-pod.yml", namespace: str='vtscanner'):
    # 加载配置
    load_kube_config()
    # 创建API实例
    api_instance = client.CoreV1Api()
    with open(yaml_path) as f:
        pod_manifest = yaml.safe_load(f)
    # 动态设置Pod名称
    pod_manifest['metadata']['name'] = generate_unique_pod_name(pod_manifest.get('metadata', {}).get('name', 'example-pod'))
    # 设置Node选择
    target_node = node_name
    # 使用nodeSelector
    pod_manifest['spec']['nodeSelector'] = {
        "kubernetes.io/hostname": target_node
    }
    # 或者使用affinity
    # pod_manifest['spec']['affinity'] = {
    #     "nodeAffinity": {
    #         "requiredDuringSchedulingIgnoredDuringExecution": {
    #             "nodeSelectorTerms": [
    #                 {
    #                     "matchExpressions": [
    #                         {
    #                             "key": "kubernetes.io/hostname",
    #                             "operator": "In",
    #                             "values": [target_node]
    #                         }
    #                     ]
    #                 }
    #             ]
    #         }
    #     }
    # }
    try:
        # 创建Pod
        api_response = api_instance.create_namespaced_pod(
            body=pod_manifest,
            namespace=namespace
        )
        logger.info(f"Pod {pod_manifest['metadata']['name']} created. status='%s'" % str(api_response.status))
        return True
    except Exception as e:
        logger.error(f"Exception when creating Pod {pod_manifest['metadata']['name']}: %s\n" % e)
        return False

if __name__ == '__main__':
    # 假设你的Pod YAML文件位于当前目录下，并且名为pod.yaml
    create_pod_from_yaml('pod.yaml', 'default')  # 根据需要更改命名空间