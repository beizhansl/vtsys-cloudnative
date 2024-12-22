base_html = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>漏洞扫描报告</title>
    <style>
        body {{
            font-family: Helvetica, sans-serif;
            margin: 40px;
            line-height: 1.6;
        }}
        h1, h2, h3 {{
            color: #333;
        }}
        table {{
            width: 100%; /* 表格宽度为100% */
            text-align: center;
            border-collapse: collapse;
            margin-bottom: 20px;
        }}
        th, td {{
            padding: 10px;
            text-align: left;
            word-wrap: break-word; /* 自动换行 */
            word-break: break-all; /* 强制断词 */
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #f2f2f2;
        }}
        .high-severity {{
            background-color: #ffdddd; /* 高危等级行的背景色 */
        }}
        .medium-severity {{
            background-color: #ffffcc; /* 中危等级行的背景色 */
        }}
        .low-severity {{
            background-color: #99ccff; /* 低危等级行的背景色 */
        }}
      .non-severity {{
            background-color: #C0C0C0; /* 低危等级行的背景色 */
        }}
    </style>
</head>
<body>
    <h1 style="text-align: center">漏洞扫描报告</h1>
    <p style="text-align: center"><strong>报告日期:</strong> 2024年9月15日</p>
    <p style="text-align: center"><strong>扫描工具:</strong> GVM/OpenVAS</p>
    <p style="text-align: center"><strong>扫描目标:</strong> 223.193.36.1</p>

    <h2>扫描概述</h2>
    <table>
            <tr>
                <td class="high-severity">高危漏洞数</td>
              	 <td class="medium-severity">中危漏洞数</td>
              <td class="low-severity">低危漏洞数</td>
                <td class="non-severity">总漏洞数</td>
            </tr>
            <tr>
              <td>{high_num}</td>
              <td>{medium_num}</td>  
              <td>{low_num}</td>
                <td>{all_num}</td>
            </tr>
    </table>

    <h2>漏洞列表</h2>

    {vuls}

</body>
</html>
"""