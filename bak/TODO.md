# 编程计划

我想基于flet做一个本地的GUI App，用于调用一个远程的服务来

## 远程服务交互GUI

实现任务创建与多个任务的监控、管理功能
每个任务的操作流程都是：
1. 【用户输入】提供一个地址栏让用户粘贴需要下载的视频网站链接，并提供两个选项：是否需要加载本地浏览器的Coockie信息，是否需要回传下载音频文件
2. ✅【Coockie加载】使用`browser-cookie3`获取本地Firefox/Edge/Chrome浏览器（可选择）上常用视频网站的Coockie信息，然后使用`README_REMOTE.md`中提供的方法对其进行加密
3. ✅【主任务请求】获得用户请求的视频网站链接，将其与加密的Cookie信息一并发送至`README_REMOTE.md`中提供的`/api/process`接口
4. ✅【状态更新】定期使用`README_REMOTE.md`中提供的`/api/status/<task_id>`接口更新任务状态并显示出来
5. ✅【获取主任务响应】等待任务响应，获得响应结果，并将任务所有的相关信息用sqlite3存入本地的`task.db`文件
6. ✅【音频下载请求与响应】如果响应结果中包含音频下载链接，立即使用`README_REMOTE.md`中提供的`/api/process`接口下载音频文件到`./download`目录
7. ✅【远程缓存清理】如果下载了音频使用`README_REMOTE.md`中提供的`/api/process`接口

## 历史任务加载 ✅

每次启动时，加载`task.db`文件中已经维护的历史任务信息（最多100条）

## 任务结果处理 ✅

对于所有已经成功的任务，基于`task.db`文件存储的文字识别结果、时间戳与音频文件路径信息提供如下功能：
1. 直接复制与阅读文字识别结果 ✅
2. 直接复制与阅读音频文件路径 ✅
3. 基于文字识别结果与时间戳信息实现智能的字幕生成导出功能（可以通过参数控制断句长度），核心功能函数已在下面提供：✅

```python
def generate_smart_srt(inference_result, min_length=10):
    """
    智能SRT生成：
    - 硬标点 (。？！)：强制换行
    - 软标点 (，、)：只有当前句长度超过 min_length 时才换行，否则合并
    """
    # 1. 提取数据
    data = inference_result[0] if isinstance(inference_result, list) else inference_result
    text = data.get('text', '')
    ts_list = data.get('timestamp', [])

    # 2. 定义标点集合
    # 硬断句：句号、问号、感叹号、分号
    hard_break_chars = set("。？！；：?!;:\n")
    # 软断句：逗号、顿号、空格
    soft_break_chars = set("，、, ")

    srt_content = ""
    sentence_idx = 1
    ts_index = 0  # 时间戳指针

    # 当前行的状态缓存
    curr_text = ""
    curr_start = -1
    curr_end = 0

    for char in text:
        # --- A. 处理时间戳 (如果是有效文字) ---
        is_punctuation = char in hard_break_chars or char in soft_break_chars or char.isspace()

        if not is_punctuation:
            if ts_index < len(ts_list):
                start, end = ts_list[ts_index]
                # 如果是当前行的第一个字
                if curr_start == -1:
                    curr_start = start
                # 更新当前行的结束时间
                curr_end = end
                ts_index += 1

        # --- B. 拼接字符 ---
        curr_text += char

        # --- C. 判断是否断句 ---
        should_flush = False

        # C1. 硬断句：遇到句号，必须断
        if char in hard_break_chars:
            should_flush = True

        # C2. 软断句：遇到逗号，看字数够不够
        elif char in soft_break_chars:
            # 只有当当前句长度 >= 设定的最小长度时，才断开
            # 否则就忽略这个逗号，继续往后拼
            if len(curr_text) >= min_length:
                should_flush = True

        # --- D. 执行断句 ---
        if should_flush and curr_text.strip():
            # 防御：万一全是标点或没时间戳
            if curr_start == -1:
                curr_start = curr_end # 兜底

            srt_content += f"{sentence_idx}\n"
            srt_content += f"{format_time(curr_start)} --> {format_time(curr_end)}\n"
            srt_content += f"{curr_text.strip()}\n\n" # strip去掉首尾空格

            sentence_idx += 1
            # 重置状态
            curr_text = ""
            curr_start = -1

    # --- E. 处理残留文本 ---
    if curr_text.strip():
        if curr_start == -1: curr_start = curr_end
        srt_content += f"{sentence_idx}\n"
        srt_content += f"{format_time(curr_start)} --> {format_time(curr_end)}\n"
        srt_content += f"{curr_text.strip()}\n\n"

    return srt_content
```


# 其他关键信息

- 远程服务的请求接口是`tkmini.local:5001`而不是`README_REMOTE.md`中的`localhost:5001`
- python使用本地的虚拟conda环境：`conda activate vg`

