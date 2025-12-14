import re
import traceback

def format_time(milliseconds):
    """将毫秒转换为SRT时间格式 (HH:MM:SS,mmm)"""
    try:
        # 将毫秒转换为秒
        seconds = milliseconds // 1000
        # 计算毫秒部分
        ms = milliseconds % 1000
        # 计算小时、分钟和秒
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        # 格式化为SRT时间格式
        result = f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"
        return result
    except Exception as e:
        # 如果转换失败，返回默认值
        print(f"时间格式转换错误: {e}")
        traceback.print_exc()  # 添加详细的错误追踪
        return "00:00:00,000"

def generate_smart_srt(inference_result, min_length=10):
    """
    智能SRT生成：
    - 硬标点 (。？！)：强制换行
    - 软标点 (，、)：只有当前句长度超过 min_length 时才换行，否则合并
    """
    try:
        # 1. 提取数据
        data = inference_result[0] if isinstance(inference_result, list) else inference_result

        # 检查数据结构，兼容不同的输入格式
        if isinstance(data, dict):
            # 尝试从不同的字段获取文本
            text = ""
            if 'text' in data:
                text = data['text']
            elif 'transcription' in data:
                text = data['transcription']
            elif 'srt' in data:
                # 如果已经有SRT内容，直接返回
                print("检测到已有的SRT内容，直接返回")
                return data['srt']

            # 获取时间戳
            ts_list = data.get('timestamp', [])

            # print(f"提取到的文本长度: {len(text)}, 时间戳数量: {len(ts_list)}")  # 添加调试信息
        else:
            print("输入数据格式不符合预期")
            return ""

        # 2. 定义标点集合
        # 硬断句：句号、问号、感叹号、分号
        hard_break_chars = set("。？！；：?!;:\n")
        # 软断句：逗号、顿号、空格
        soft_break_chars = set(".，、, ")

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

        # print(f"生成的SRT内容长度: {len(srt_content)}")  # 添加调试信息
        return srt_content
    except Exception as e:
        print(f"生成SRT字幕时出错: {e}")
        traceback.print_exc()  # 添加详细的错误追踪
        return ""

def is_mainly_cjk(text):
    """
    判断文本是否主要包含中日韩字符 (CJK)
    只要包含一定比例的 CJK 字符，就认为应当使用短句策略
    """
    if not text:
        return False
        
    # CJK 统一表意文字范围 (中文) + 日文平片假名 + 韩文音节
    # \u4e00-\u9fff : 中文
    # \u3040-\u309f : 日文平假名
    # \u30a0-\u30ff : 日文片假名
    # \uac00-\ud7af : 韩文
    cjk_pattern = re.compile(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]')
    
    # 统计前 500 个字符即可（提高效率），如果有超过 5% 是 CJK，就认为是 CJK 语境
    sample = text[:500]
    matches = cjk_pattern.findall(sample)
    
    # 如果 CJK 字符占比超过 15% (避免英文视频里偶尔出现个别汉字的情况)
    if len(sample) > 0 and (len(matches) / len(sample)) > 0.15:
        return True
    return False