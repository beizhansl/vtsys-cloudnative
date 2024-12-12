import kopf
import kubernetes.client as k8s_client
from kubernetes.config import load_incluster_config
from kubernetes.client.rest import ApiException
from paramiko import SSHClient
from scp import SCPClient
from paramiko import AutoAddPolicy

# 加载集群内的配置（如果从集群外部运行，则需要调整）
load_incluster_config()

batch_v1 = k8s_client.BatchV1Api()
core_v1 = k8s_client.CoreV1Api()

def scp_copy_with_paramiko(src, remote_path, hostname, username, key_filename=None, password=None):
    try:
        # 初始化SSH客户端并自动添加主机到known_hosts
        with SSHClient() as ssh:
            ssh.set_missing_host_key_policy(AutoAddPolicy())
            ssh.connect(hostname=hostname, username=username, look_for_keys=True, key_filename=key_filename, password=password)

            # SCPCLient采取与SSHClient相同的参数
            with SCPClient(ssh.get_transport()) as scp:
                scp.put(src, remote_path)
        
        print("File copied successfully.")
        return True
    except Exception as e:
        print(f"An error occurred while copying the file: {str(e)}")
        return False

@kopf.on.create('node')
def node_created(spec, name, **kwargs):
    # 检查节点是否已经具有 'data=ready' 标签
    hostname = ""
    try:
        node = core_v1.read_node(name)
        if node.metadata.labels and 'data' in node.metadata.labels and node.metadata.labels['data'] == 'ready':
            kopf.info(f"Node {name} already has the 'data=ready' label.")
            return
        for address in node.status.addresses:
            if address.type == "Hostname":
                hostname = address.adress
        if hostname == "":
            raise Exception(f"Failed to get hostname from node {name}") 
    except ApiException as e:
        kopf.info(f"Failed to read node {name}: {e}")
        raise

    kopf.info(f"New node detected: {name}. Creating data copy job.")

    # 拷贝需要的数据文件，从旧节点/data拷贝到新节点的/data中
    try: 
        scp_copy_with_paramiko('/data/', '/data/openvas/', 'hostB', 'root')
        kopf.info(f"SCP copy succeeded for node {name}.")
    except ApiException as e:
        kopf.info(f"SCP copy failed for node {name}: {e}")
        raise
    
    # 更新节点标签
    try:
        node.metadata.labels = {'data': 'ready'}
        core_v1.patch_node(name, node)
        kopf.info(f"Updated node {name} with 'data=ready' label.")
    except ApiException as e:
        kopf.info(f"Failed to update node {name}: {e}")
        raise

if __name__ == "__main__":
    kopf.run()