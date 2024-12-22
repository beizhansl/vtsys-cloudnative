from pygvm.exceptions import AuthenticationError
from pygvm.pygvm import Pygvm
from gvm.connections import UnixSocketConnection, TLSConnection
from gvm.protocols.latest import Gmp
from gvm.transforms import EtreeTransform
from config import settings, logger
from zapv2 import ZAPv2
from config import logger
from pygvm.pygvm import Pygvm
from pygvm.exceptions import HTTPError
from config import settings
import requests
from sqlctrl import insert_splite_task, get_splite_task


def get_gvm_conn() -> Pygvm:
    connection = None
    if settings.gvmdtype == "unix":
        unixsockpath = settings.unixsockpath
        connection = UnixSocketConnection(path=unixsockpath)
    elif settings.gvmdtype == "tls":
        capath = settings.tlscapath
        certpath = settings.tlscertpath
        keypath = settings.tlskeypath
        connection = TLSConnection(hostname=settings.gvmdhost, 
                                    port=settings.gvmdport, 
                                    cafile=capath,
                                    certfile=certpath,
                                    keyfile=keypath)
    transform = EtreeTransform()
    gmp = Gmp(connection, transform=transform)
    pyg = Pygvm(gmp=gmp, username=settings.username, passwd=settings.password)
    if pyg.checkauth() is False:
        raise AuthenticationError()
    return pyg

def create_ff_config(pyg: Pygvm, ffid:str, splite_num:int):
    config_ids = {}
    whole_families = {}
    config_num = {} 
    config_family = {}
    for num in range(splite_num):
        config_name = "FF"+str(splite_num)+"_"+str(num)
        resp = pyg.create_config(config_name, ffid, "Created by scan_server")
        # 调整配置
        config_id = resp.data["@id"]
        config_num[config_id] = 0
        config_family[config_id] = []
        resp = pyg.get_config(config_id)
        family_list = resp.data["families"]["family"]
        for family in family_list:
            family_name = family["name"]
            if family_name in whole_families:
                continue
            nvts = pyg.list_config_nvts(details=False, config_id=config_id, family=family_name)
            # 获取所有oid
            oid_list = []
            for nvt in nvts:
                oid_list.append(nvt["@oid"])
            # 获取num~num+1/splite_num区间oid
            all_nvt_num = len(oid_list) 
            nvt_num = len(oid_list) // splite_num
            if num == splite_num-1:
                oid_list = oid_list[num*nvt_num:]
            else:
                oid_list = oid_list[num*nvt_num: (num+1)*nvt_num]
            # 设置
            try:
                pyg.modify_config_nvt(config_id=config_id, family=family_name, nvt_oids=oid_list)
                config_family[config_id].append(family_name)
            except HTTPError as e:
                if "whole-only" in str(e):
                    whole_families[family_name] = all_nvt_num
                else:
                    raise
        config_ids[config_name] = config_id
    # 调整whole-family部分
    # print(whole_families)
    
    sorted_families = sorted(whole_families.items(),key = lambda x:x[1],reverse = True)
    for family_name, all_nvt_num in sorted_families:
        min_config = None
        min_num = 1000000000
        for config, num in config_num.items():
            if min_num > num:
                min_config = config
                min_num = num
        if min_config is not None:
            config_family[min_config].append(family_name)
            config_num[min_config] = num + all_nvt_num       
    # print(config_family)
    # return []
    for config_id, families in config_family.items():
        families_tuple = []
        for family_name in families:
            if family_name in whole_families:
                families_tuple.append((family_name, True, True))
            else:
                families_tuple.append((family_name, True, False))
        pyg.modify_config_family(config_id=config_id, families=families_tuple)    
    
    return config_ids


def check_splited_configs(pyg: Pygvm, splite_num: int):
    configs = pyg.list_configs()
    config_name = "FF" + str(splite_num)
    config_ids = {}
    ffid = None
    for config in configs:
        # 创建以Full and fast为蓝本
        if config["name"] == "Full and fast":
            ffid = config["@id"]            
        if config_name in config["name"]:
            config_ids[config["name"]] = config["@id"]

    if len(config_ids.keys()) != splite_num:
        # 全部删除重新创建
        for config_id in config_ids.values():
            try:
                pyg.delete_config(config_id)
            except Exception as e:
                logger.error("Delete config error: %s", str(e))
                return False, "DeleteConfigFailed", None
        config_ids = {}
    
    if len(config_ids.keys()) == 0:
        try:
            config_ids = create_ff_config(pyg=pyg, ffid=ffid, splite_num=splite_num)        
        except Exception as e:
            logger.error("Create config error: %s", str(e))
            print(e.with_traceback())
            return False, "CreateConfigFailed", None
    
    if len(config_ids.keys()) != splite_num:
        return False, "ConfigNumError", None
    
    return True, None, config_ids


def map_to_scanners(splite_num:int, target:str, id: str):
    scanner_list = settings.scanner_list
    scanner_task_list = []
    for scanner_host in scanner_list:
        url = f"http://{scanner_host}/gvm/get_task_num"
        try:
            resp = requests.get(
                url,
                headers={'secret-key':settings.secret_key}
            )
            resp.raise_for_status()
            data = resp.json()
            if not data['ok']:
                logger.error(f"Get task num from gvm {scanner_host} failed, {data['errmsg']}")
            task_num = data['task_num']
            scanner_task_list.append([scanner_host, task_num])
        except Exception as e:
            logger.error(f"Get task num from gvm {scanner_host} failed, {str(e)}")
            continue
    scanner_task_list = sorted(scanner_task_list, key=lambda x:x[1], reverse=False)
    if len(scanner_task_list) == 0:
        return False, "NoScannerAvailable"
    
    max_task_num = settings.max_task_num
    creatable_task_num = 0
    for scanner_task in scanner_task_list:
        creatable_task_num += max_task_num - scanner_task[1]
    if creatable_task_num < splite_num:
        return False, "NoEnoughScanner"
    
    # 分发下去
    for num in range(splite_num):
        while(True):
            scanner_num = len(scanner_task_list)
            if scanner_num == 0:
                return False, "NoScannerAvailable"
            idx = scanner_num-1
            for i in range(scanner_num):
                if i == scanner_num-1:
                    break
                elif scanner_task_list[i][1] < scanner_task_list[i+1][1]:
                    idx = i
                    break
                else:
                    continue    
            scanner_host = scanner_task_list[idx][0]
            try:
                url = f"http://{scanner_host}/gvm/create_task_with_config"
                resp = requests.post(
                    url,
                    headers={'secret-key':settings.secret_key},
                    params={'target':target, 'id':id, 'num':num, 'splite_num':splite_num}
                )
                resp.raise_for_status()
                data = resp.json()
                if not data['ok']:
                    logger.error(f"Map task num to gvm {scanner_host} failed, {data['errmsg']}")
                    scanner_task_list.pop(idx)
                # 存起来到数据库中
                task_id = data['running_id']
                logger.info("Insert task into db...")
                ok = insert_splite_task(id=id, task_id=task_id, scanner=scanner_host)
                if not ok:
                    logger.error(f"Map task num to gvm {scanner_host} failed, insert into tasks error")
                    return False, "InsertTasksError"
                scanner_task_list[i][1] += 1
                break
            except Exception as e:
                logger.error(f"Get task num from gvm {scanner_host} failed, {str(e)}")
                scanner_task_list.pop(idx)
                continue
    return True, None
    

def get_splite_task_status(id: str):
    tasks = get_splite_task(id=id)
    # 获取每一个task的状态
    unfinished_num = 0
    num = 0
    for task in tasks:
        scanner_host = task[0]
        task_id = task[1]
        try:
            url = f"http://{scanner_host}/gvm/get_task"
            resp = requests.post(
                url,
                headers={'secret-key':settings.secret_key},
                params={'running_id':task_id}
            )
            data = resp.json()
            if not data['ok']:
                logger.error(f"Reduce task from gvm {scanner_host} failed, {data['errmsg']}")
                return False, "ReduceGetTaskError", 0
            status = data["running_status"]
            if status != "Done":
                unfinished_num += 1
            num += 1
        except Exception as e:
            logger.error(f"Reduce task from gvm {scanner_host} failed, {str(e)}")
            return False, "ReduceGetTaskError", 0
    if unfinished_num != 0:
        return True, unfinished_num, num
    return True, unfinished_num, num
   

def reduce_splite_task(id: str):
    tasks = get_splite_task(id=id)
    results = []
    hase = []
    for task in tasks:
        scanner_host = task[0]
        task_id = task[1]
        try:
            url = f"http://{scanner_host}/gvm/get_task_result"
            resp = requests.post(
                url,
                headers={'secret-key':settings.secret_key},
                params={'running_id':task_id}
            )
            data = resp.json()
            if not data['ok']:
                logger.error(f"Get task result from gvm {scanner_host} failed, {data['errmsg']}")
                return False, "GetTaskResultError"
            sub_results = resp["vuls"]
            for sub_result in sub_results:
                if "nvt" in sub_result and "@oid" in sub_result["nvt"]:
                    oid = sub_result["nvt"]["@oid"]
                else:
                    oid = sub_result["name"]
                if oid in hase:
                    continue
                hase.append(oid)
                results.append(sub_result)
        except Exception as e:
            logger.error(f"Get task result from gvm {scanner_host} failed, {str(e)}")
            return False, "GetTaskResultError"
    return True, results              


def delete_splite_task_with_id(id: str):
    tasks = get_splite_task(id=id)
    for task in tasks:
        scanner_host = task[0]
        task_id = task[1]
        try:
            url = f"http://{scanner_host}/gvm/delete_task"
            resp = requests.post(
                url,
                headers={'secret-key':settings.secret_key},
                params={'running_id':task_id}
            )
            data = resp.json()
            if not data['ok']:
                logger.error(f"Delete task from gvm {scanner_host} failed, {data['errmsg']}")
                return False, "DeleteTaskError"
        except Exception as e:
            logger.error(f"Delete task from gvm {scanner_host} failed, {str(e)}")
            return False, "DeleteTaskError"
    return True, None      

