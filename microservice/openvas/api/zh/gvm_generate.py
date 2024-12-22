from datetime import datetime, timedelta
import re as regex
from sqlcve import CveSql
import html
from config import logger

sql = CveSql()

def format_str(value: str):
    value = html.escape(value)
    value = value.replace("\n \n", " <br /> ")
    value = value.replace("\n\n", " <br /> ")
    value = value.replace("\n", " <br /> ")
    return value

def get_vnl_en(vuln: dict):
    vnl_en = ""
    if "detection" in vuln:
        detetction_str = " <b> Product Detection Result </b> <br /> "
        if "result" in vuln["detection"] and "details" in vuln["detection"]["result"] and "detail" in vuln["detection"]["result"]["details"]:
            detections = vuln["detection"]["result"]["details"]["detail"]
            for detection in detections:
                value = detection["value"]
                if isinstance(value, str):
                    value = format_str(value)
                    detetction_str +=  detection["name"] + ": " + value +   " <br /> "        
            vnl_en += detetction_str
    if "description" in vuln:
        detetction_str = " <b> Detection Result </b> <br /> "
        detectionstr = vuln["description"]
        if isinstance(detectionstr, str):   
            value = format_str(detectionstr)
            detetction_str += value + " <br /> "
            vnl_en += detetction_str
    if "nvt" in vuln and "tags" in vuln["nvt"]:
        tag_str = ""
        tags_str = vuln["nvt"]["tags"]
        tags = []
        if isinstance(tags_str, str):
            tags = tags_str.split("|")
        for tag in tags:
            kv = tag.split("=")
            value = format_str(kv[1])
            if value == ""  or value is None:
                continue
            if kv[0] in ["summary", "insight", "impact"]:
                tag_str += " <b> " + kv[0].capitalize() + " </b> " + " <br />" + value + " <br /> "
            elif kv[0] == "affected":
                tag_str += " <b> Affected Software/OS </b> " + " <br /> " + value + " <br /> "
            elif kv[0] == "vuldetect":
                tag_str += " <b> Detection Method </b> " + " <br /> " + value + " <br /> "
        vnl_en += tag_str
    return vnl_en
    
def trans_time(utc_time_str: str):
    utc_time = datetime.strptime(utc_time_str, "%Y-%m-%dT%H:%M:%SZ")
    beijing_offset = timedelta(hours=8)
    beijing_time = utc_time + beijing_offset
    return beijing_time.strftime('%Y-%m-%d %H:%M:%S')

def format_vulnerability(vuln: dict):
    servity = "安全"
    severity_class = 'non-severity'
    if vuln['threat'] == 'High':
        severity_class = 'high-severity'
        servity = "高危"
    elif vuln['threat'] == 'Medium':
        severity_class = 'medium-severity'
        servity = "中危"
    elif vuln['threat'] == 'Low':
        severity_class = 'low-severity'
        servity = "低危"

    refstr = ""
    cve_id_list = []
    num = 0
    if "nvt" in vuln and "refs" in vuln["nvt"] and "ref" in vuln["nvt"]["refs"]:
        ref_list = vuln["nvt"]['refs']["ref"]
        if isinstance(ref_list, list):
            for ref in ref_list:
                if "@type" in ref and ref['@type'] == 'cve':
                    cve_id_list.append(ref['@id'])
                if num == 5:
                    break
                num += 1
                ref_str = format_str(ref['@type'] + ": " + ref['@id'])
                refstr += ref_str + " <br /> "
        elif isinstance(ref_list, dict):
            if "@type" in ref_list and ref_list['@type'] == 'cve':
                cve_id_list.append(ref_list['@id'])
            ref_str = format_str(ref_list['@type'] + ": " + ref_list['@id'])
            refstr += ref_str + " <br /> "
    
    title = vuln["name"]
    cvss = vuln["severity"]
    modification_time = trans_time(vuln["modification_time"])
    
    solution_en = ""
    if "nvt" in vuln and "solution" in vuln["nvt"]:
        if "@type" in vuln["nvt"]["solution"]:
            solution_en = vuln["nvt"]["solution"]["@type"] + ": "
        if "#text" in vuln["nvt"]["solution"]:
            solution_en += vuln["nvt"]["solution"]["#text"]
    solution_en = format_str(solution_en)
    solution = solution_en
    
    # 获取中文漏洞信息
    zh = False
    data = None
    # qod = vuln["qod"]["value"]
    port = vuln["port"]
    # 整合英文信息
    description_en = get_vnl_en(vuln)
    description = description_en
    
    if cve_id_list:
        for cve_id in cve_id_list:
            zh, data = sql.find_vul(cve_id)
            if zh:
                break
    if zh:
        if data[8] is not None:
            title = data[8]
        if data[9] is not None:
            solution = data[9] + " <br /> " + solution_en
        if data[11] is not None:
            description = data[11] + " <br /> " + description_en
    
    return f"""
    <div>
        <h3>{title}</h3>
        <table>
            <tr class="{severity_class}">
                <td style="width:10%">严重性</td>
                <td style="width:90%">{servity}</td>
            </tr>
            <tr>
                <td style="width:10%">发现时间</td>
                <td style="width:90%">{modification_time}</td>
            </tr>
            <tr>
                <td style="width:10%">漏洞描述</td>
                <td style="width:90%">{description}</td>
            </tr>
            <tr>
                <td style="width:10%">CVSS评分</td>
                <td style="width:90%">{cvss}</td>
            </tr>
            <tr>
                <td style="width:10%">扫描端口</td>
                <td style="width:90%">{port}</td>
            </tr>
            <tr>
                <td style="width:10%">建议措施</td>
                <td style="width:90%">{solution}</td>
            </tr>
            <tr>
                <td style="width:10%">参考资料</td>
                <td style="width:90%">{refstr}</td>
            </tr>
        </table>
    </div>
    """