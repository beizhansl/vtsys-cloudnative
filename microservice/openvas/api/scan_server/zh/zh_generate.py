from zh.base import base_html
from zh.gvm_generate import format_vulnerability
import json
from pygvm.response import Response
from config import logger

def gvm_zh_report(vuls: list):
    html_str = base_html
    high_num = 0
    medium_num = 0
    low_num = 0
    vul_list = []
    for vul in vuls:
        try:
            vuln = format_vulnerability(vul)
            vul_list.append(vuln)
        except Exception as e:
                logger.error("Failed to format vuln: %s, error: %s", str(e)) 
                continue
        if vul['threat'] == 'High':
            high_num += 1
        elif vul['threat'] == 'Medium':
            medium_num += 1
        elif vul['threat'] == 'Low':
            low_num += 1

    all_num = high_num + medium_num + low_num
    vulstr = "\n".join(vul_list)
    # print(vulstr)

    if isinstance(html_str, str):
        html_str = html_str.format(
            high_num=high_num,
            medium_num=medium_num,
            low_num=low_num,
            all_num=all_num,
            vuls=vulstr
        )
    return html_str
    # print(html_str)
