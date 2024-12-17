from kubernetes import config
from kubernetes.config.config_exception import ConfigException

def load_kube_config():
    """
    尝试加载集群内部或外部的 Kubernetes 配置。
    如果在集群内，则使用 incluster 配置；如果在集群外，则加载本地 kubeconfig 文件。
    """
    try:
        # 尝试加载集群内的配置
        config.load_incluster_config()
        
    except ConfigException:
        try:
            # 如果失败，则尝试加载本地配置文件
            config.load_kube_config()
        except ConfigException as e:
            raise Exception("Could not configure kubernetes python client: %s" % e)

# 如果希望在导入时自动加载配置，可以在文件末尾调用该函数
if __name__ == '__main__':
    load_kube_config()