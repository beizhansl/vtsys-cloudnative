from zapv2 import ZAPv2
import os
from model.zap_task import InternStatus

http_proxy = os.getenv("HTTP_PROXY", "127.0.0.1")
api_key = os.getenv("API_KEY", "cstcloud")
zap_max_thread = int(os.getenv("ZAP_MAX_THREAD", "2"))

def get_zap_conn() -> ZAPv2:
    zap = ZAPv2(proxies={'http':http_proxy}, apikey=api_key)
    res = zap.pscan.set_max_alerts_per_rule(20)
    if res != 'OK':
        raise Exception("Set max alerts per rule failed.") 
    return zap

def handle_zap_task(zap: ZAPv2, running_status:str, target:str):
    if running_status == InternStatus.SPIDER:
        progress = int(zap.spider.status(0))
        # 传统爬虫完成进入Ajax爬虫
        if progress >= 100:
            zap.ajaxSpider.set_option_max_crawl_depth(5)
            zap.ajaxSpider.set_option_max_duration(10)
            zap.ajaxSpider.set_option_browser_id('htmlunit')
            zap.ajaxSpider.set_option_number_of_browsers(zap_max_thread)
            res = zap.ajaxSpider.scan(target)
            if res != 'OK':
                raise Exception("AjaxSpider begin failed.")
            running_status = InternStatus.AJAXSPIDER
    # 2. 进入ajax爬虫期间
    if running_status == InternStatus.AJAXSPIDER:
        status = zap.ajaxSpider.status
        # ajax爬虫完成进入主动扫描
        if status != 'running':
            zap.ascan.set_option_max_scan_duration_in_mins(15)
            zap.ascan.set_option_max_rule_duration_in_mins(1)
            # 控制线程并发数
            zap.ascan.set_option_thread_per_host(zap_max_thread)
            # 主动扫描加速
            zap.ascan.set_option_max_alerts_per_rule(1)
            zap.ascan.set_option_max_results_to_list(1)
            zap.ascan.set_option_max_chart_time_in_mins(0)
            res = zap.ascan.scan(target)
            # url无效，扫描结束
            if res == 'url_not_found':
                running_status = InternStatus.FAILED
                return running_status, res
            elif int(res) != 0:
                raise Exception(f"Active scan failed.")
            else:
                running_status = InternStatus.ACTIVE
    # 3. 进入主动扫描期间
    if running_status == InternStatus.ACTIVE:
        progress = int(zap.ascan.status(0))
        # 主动扫描完成，进入被动扫描
        if progress >= 100:
            pscan = int(zap.pscan.records_to_scan)
            if pscan == 0:
                running_status = InternStatus.DONE
            else:
                running_status = InternStatus.PASSIVE
    # 4. 进入passive扫描期间
    if running_status == InternStatus.PASSIVE:
        pscan = int(zap.pscan.records_to_scan)
        # 快速退出passive期间
        if pscan < 10:
            running_status = InternStatus.DONE
    return running_status, None
