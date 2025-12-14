# -*- coding: utf-8 -*-
import flet as ft
import os
import sys
import rookiepy
import requests
import json
import traceback
import asyncio
import aiohttp
from pathvalidate import sanitize_filename
from datetime import datetime
from collections.abc import Mapping
from db_handler import DatabaseHandler
from audio_downloader import download_audio_file, cleanup_remote_audio
from crypto_utils import encrypt_data

# 设置设置环境变量以及默认编码UTF-8
if sys.version_info[0] == 3 and sys.version_info[1] >= 7:
    # 对于Python 3.7及以上版本
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)
sys.stdout.reconfigure(line_buffering=True)
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['NO_PROXY'] = '.local,127.0.0.1,localhost'

# 获取指定浏览器的Cookie
def get_cookies_via_rookie(browser_name):
    print(f"正在使用 rookiepy 从 {browser_name} 读取...")
    if browser_name in ['chrome', 'Chrome']:
        cookies = rookiepy.chrome()
    elif browser_name in ['firefox', 'Firefox']:
        cookies = rookiepy.firefox()
    elif browser_name == ['edge', 'Edge']:
        cookies = rookiepy.edge()
    else:
        raise ValueError("不支持的浏览器")
    lines = ["# Netscape HTTP Cookie File"]
    for c in cookies:
        # rookiepy 返回的是字典或者类似结构，通常包含 domain, path, secure, expires, name, value
        # 注意：rookiepy 的 expires 可能是 None
        domain = c.get('domain', '')
        flag = "TRUE" if domain.startswith('.') else "FALSE"
        path = c.get('path', '/')
        secure = "TRUE" if c.get('secure', False) else "FALSE"
        exp = c.get('expires')
        expires = str(int(exp)) if exp else "0"
        name = c.get('name', '')
        value = c.get('value', '')
        lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}")
    return "\n".join(lines)


# 初始化数据库
def init_db():
    db_handler = DatabaseHandler()
    return db_handler

# 发送主任务请求到远程服务
def send_main_task_request(url, encrypted_cookie_data=None, keep_audio=False):
    """
    发送主任务请求到远程服务

    Args:
        url (str): 视频链接
        encrypted_cookie_data (str, optional): 加密的Cookie数据
        keep_audio (bool): 是否保留音频文件

    Returns:
        dict: 包含请求结果的字典
            - success (bool): 请求是否成功
            - task_id (str): 任务ID（成功时）
            - message (str): 结果消息
            - error (str): 错误信息（失败时）
    """
    try:
        # 构造API请求URL
        api_url = "http://tkmini.local:5001/api/process"

        # 构造请求头
        headers = {
            "Content-Type": "application/json"
        }

        # 构造请求体
        payload = {
            "url": url,
            "keep_audio": keep_audio
        }

        # 如果有加密的Cookie数据，则添加到请求中
        if encrypted_cookie_data:
            payload["encrypted_cookie_data"] = encrypted_cookie_data

        # 发送POST请求
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)

        # 检查响应状态码，202表示请求已接受，正在处理中
        if response.status_code in [200, 202]:
            # 解析JSON响应
            result = response.json()

            # 检查响应中是否包含任务ID
            if "task_id" in result:
                return {
                    "success": True,
                    "task_id": result["task_id"],
                    "message": result.get("message", "任务已启动"),
                    "error": None
                }
            else:
                return {
                    "success": False,
                    "task_id": None,
                    "message": "响应中缺少任务ID",
                    "error": "Missing task_id in response"
                }
        else:
            # 处理HTTP错误
            error_details = {
                "status_code": response.status_code,
                "response_text": response.text,
                "headers": dict(response.headers)
            }
            print(f"HTTP错误详情: {json.dumps(error_details, ensure_ascii=False, indent=2)}")  # 添加详细日志输出
            return {
                "success": False,
                "task_id": None,
                "message": f"HTTP错误 {response.status_code}",
                "error": response.text
            }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "task_id": None,
            "message": "请求超时",
            "error": "Request timeout"
        }
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "task_id": None,
            "message": "连接错误，请检查网络或服务器状态",
            "error": "Connection error"
        }
    except requests.exceptions.RequestException as e:
        print(f"请求异常详情: {str(e)}")  # 添加详细日志输出
        return {
            "success": False,
            "task_id": None,
            "message": "请求异常",
            "error": str(e)
        }
    except json.JSONDecodeError as e:
        print(f"JSON解析错误详情: {str(e)}")  # 添加详细日志输出
        return {
            "success": False,
            "task_id": None,
            "message": "响应解析失败",
            "error": f"Failed to parse JSON response: {str(e)}"
        }
    except Exception as e:
        print(f"未知错误详情: {str(e)}")  # 添加详细日志输出
        return {
            "success": False,
            "task_id": None,
            "message": "未知错误",
            "error": str(e)
        }

# 定时轮询任务状态的类
class TaskStatusPoller:
    def __init__(self, page: ft.Page, task_id: str, status_display: ft.Column, db_handler: DatabaseHandler, load_history_tasks_func):
        self.page = page
        self.task_id = task_id
        self.status_display = status_display
        self.db_handler = db_handler
        self.load_history_tasks = load_history_tasks_func  # 保存刷新历史任务列表的函数引用
        self.is_polling = False

    async def start_polling(self):
        """开始轮询任务状态"""
        self.is_polling = True
        print(f"开始轮询任务状态，任务ID: {self.task_id}")  # 添加终端日志输出
        while self.is_polling:
            try:
                # 使用aiohttp发送异步GET请求
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"http://tkmini.local:5001/api/status/{self.task_id}", timeout=30) as response:
                        print(f"收到状态响应，状态码: {response.status}")  # 添加终端日志输出
                        if response.status == 200:
                            result = await response.json()
                            print(f"解析到的响应数据: {str(result)[:200]}")  # 添加终端日志输出
                            await self.update_ui_with_result(result)

                            # 如果任务已完成或失败，停止轮询
                            if result.get("status") in ["completed", "failed"]:
                                self.is_polling = False
                                print(f"任务已完成或失败，停止轮询，最终状态: {result.get('status')}")  # 添加终端日志输出
                                break
                        else:
                            # 处理HTTP错误，确保错误消息可以正确编码
                            error_msg = f"HTTP错误 {response.status}"
                            await self.update_status_display(error_msg, ft.Colors.RED)
                            # 确保传递给数据库的错误消息是可编码的
                            safe_error_msg = error_msg.encode('utf-8', errors='ignore').decode('utf-8')
                            self.db_handler.save_task_error(self.task_id, safe_error_msg)
                            self.is_polling = False
                            print(f"轮询过程中发生HTTP错误: {error_msg}")  # 添加终端日志输出
                            break
            except asyncio.TimeoutError:
                error_msg = "请求超时"
                await self.update_status_display(error_msg, ft.Colors.RED)
                # 确保传递给数据库的错误消息是可编码的
                safe_error_msg = error_msg.encode('utf-8', errors='ignore').decode('utf-8')
                self.db_handler.save_task_error(self.task_id, safe_error_msg)
                self.is_polling = False
                print(f"轮询超时错误: {error_msg}")  # 添加终端日志输出
                break
            except aiohttp.ClientError as e:
                error_msg = f"连接错误: {str(e)}"
                await self.update_status_display(error_msg, ft.Colors.RED)
                # 确保传递给数据库的错误消息是可编码的
                safe_error_msg = error_msg.encode('utf-8', errors='ignore').decode('utf-8')
                self.db_handler.save_task_error(self.task_id, safe_error_msg)
                self.is_polling = False
                print(f"轮询连接错误: {error_msg}")  # 添加终端日志输出
                break
            except Exception as e:
                error_msg = f"未知错误: {str(e)}"
                await self.update_status_display(error_msg, ft.Colors.RED)
                # 确保传递给数据库的错误消息是可编码的
                safe_error_msg = error_msg.encode('utf-8', errors='ignore').decode('utf-8')
                self.db_handler.save_task_error(self.task_id, safe_error_msg)
                self.is_polling = False
                print(f"轮询未知错误: {error_msg}")  # 添加终端日志输出
                break

            # 等待5秒后再次轮询
            await asyncio.sleep(5)

    async def update_ui_with_result(self, result):
        """更新UI界面和数据库"""
        old_status = self.db_handler.get_task_by_id(self.task_id).get('status', 'unknown')
        task_status = result.get("status", "unknown")
        task_progress = result.get("progress", "未知进度")
        print(f"收到任务状态更新: 状态={task_status}, 进度={task_progress}")  # 添加终端日志输出

        # 确保进度信息是字符串并且可以正确编码
        if not isinstance(task_progress, str):
            task_progress = str(task_progress)

        # 根据任务状态设置颜色
        status_color = ft.Colors.GREEN if task_status == "completed" else \
                      ft.Colors.RED if task_status == "failed" else \
                      ft.Colors.BLUE

        # 更新UI状态显示
        self.status_display.controls.clear()
        self.status_display.controls.append(ft.Text(f"任务状态: {task_status}", size=16, color=status_color))
        self.status_display.controls.append(ft.Text(f"进度: {task_progress}", size=14))

        # 如果有额外信息，也显示出来
        if "message" in result:
            message = result['message']
            # 确保消息是字符串并且可以正确编码
            if not isinstance(message, str):
                message = str(message)
            self.status_display.controls.append(ft.Text(f"信息: {message}", size=14))

        self.page.update()

        # 更新数据库状态
        self.db_handler.update_task_status(self.task_id, task_status, task_progress)

        # 如果任务已完成，处理结果
        if task_status == "completed":
            if "result" in result and isinstance(result["result"], Mapping):
                now = datetime.now()
                result["result"]["datestr"] = f"{now:%y%m%d}"
            await self.save_result_to_db(result)
        
        should_refresh_history = False
        if task_status in ["completed", "failed"]:
            should_refresh_history = True

        # 刷新历史任务列表以更新状态显示
        if old_status != task_status and should_refresh_history and hasattr(self, 'load_history_tasks') and self.load_history_tasks:
            self.load_history_tasks()

    async def update_status_display(self, message, color=ft.Colors.BLACK):
        """更新状态显示"""
        # 确保消息是字符串并且可以正确编码
        if not isinstance(message, str):
            message = str(message)

        self.status_display.controls.clear()
        self.status_display.controls.append(ft.Text(message, size=16, color=color))
        self.page.update()
        print(f"状态更新: {message}")  # 添加终端日志输出

    async def save_result_to_db(self, result):
        """保存任务结果到数据库"""
        try:
            # 保存结果到数据库
            if self.db_handler.save_task_result(self.task_id, result.get("result", {})):
                self.status_display.controls.append(ft.Text("结果已保存到数据库", size=14, color=ft.Colors.GREEN))

            # 如果需要下载音频且结果中有音频URL，则下载音频
            if result.get("result", {}).get("audio_url"):
                audio_url = result["result"]["audio_url"]
                result_datestr = result["result"].get("datestr", "251212")
                result_uploader = result["result"].get("uploader", "未知作者")
                result_title = result["result"].get("title", "未知标题")

                # 下载音频文件
                audio_file_path = download_audio_file(self.task_id, audio_url, self.db_handler, result_datestr, result_uploader, result_title)
                if audio_file_path:
                    self.status_display.controls.append(ft.Text(f"音频文件已下载: {audio_file_path}", size=14, color=ft.Colors.GREEN))

                    # 清理远程音频文件
                    if cleanup_remote_audio(self.task_id):
                        self.status_display.controls.append(ft.Text("远程音频文件已清理", size=14, color=ft.Colors.GREEN))
                    else:
                        self.status_display.controls.append(ft.Text("远程音频文件清理失败", size=14, color=ft.Colors.ORANGE))
                else:
                    self.status_display.controls.append(ft.Text("音频文件下载失败", size=14, color=ft.Colors.RED))

            self.page.update()
        except Exception as e:
            error_msg = f"保存结果时出错: {str(e)}"
            self.status_display.controls.append(ft.Text(error_msg, size=14, color=ft.Colors.RED))
            self.db_handler.save_task_error(self.task_id, error_msg)
            self.page.update()

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

            print(f"提取到的文本长度: {len(text)}, 时间戳数量: {len(ts_list)}")  # 添加调试信息
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

        print(f"生成的SRT内容长度: {len(srt_content)}")  # 添加调试信息
        return srt_content
    except Exception as e:
        print(f"生成SRT字幕时出错: {e}")
        traceback.print_exc()  # 添加详细的错误追踪
        return ""

def main(page: ft.Page):
    global selected_task_id
    selected_task_id = None

    # 页面基本设置
    page.title = "Video to Text Converter"
    page.window_width = 1200
    page.window_height = 800
    page.theme_mode = ft.ThemeMode.SYSTEM

    # 初始化数据库
    db_handler = init_db()

    # 控件定义
    # 1. 视频链接输入框
    url_input = ft.TextField(
        label="视频链接",
        hint_text="请输入视频网站链接",
        expand=True,
        text_size=14
    )

    # 2. 浏览器选择下拉框
    browser_dropdown = ft.Dropdown(
        label="浏览器选择",
        options=[
            ft.dropdown.Option("Firefox"),
            ft.dropdown.Option("Edge"),
            ft.dropdown.Option("Chrome")
        ],
        value="Firefox",
        width=150
    )

    # 3. 是否加载Cookie的复选框
    cookie_checkbox = ft.Checkbox(
        label="加载本地浏览器Cookie",
        value=False
    )

    # 4. 是否回传下载的复选框
    download_checkbox = ft.Checkbox(
        label="回传下载音频",
        value=False
    )

    # 5. 任务提交按钮
    def on_submit_click(e):
        # 获取输入值
        url = url_input.value
        browser = browser_dropdown.value
        use_cookie = cookie_checkbox.value
        return_download = download_checkbox.value

        # 验证输入
        if not url:
            page.snack_bar = ft.SnackBar(
                content=ft.Text("请输入视频链接"),
                bgcolor=ft.Colors.RED_500
            )
            page.snack_bar.open = True
            page.update()
            return

        # 显示正在处理状态
        status_display.controls.clear()
        status_display.controls.append(ft.Text("正在处理...", size=16, color=ft.Colors.BLUE))
        status_display.controls.append(ft.ProgressRing())
        page.update()

        # 获取Cookie（如果需要）
        encrypted_cookie_data = None
        if use_cookie:
            try:
                # 获取浏览器Cookie
                cookie_data = get_cookies_via_rookie(browser)
                if cookie_data is None:
                    status_display.controls.clear()
                    status_display.controls.append(ft.Text(f"获取{browser}浏览器Cookie失败", size=16, color=ft.Colors.RED))
                    page.update()
                    return

                if not cookie_data:
                    status_display.controls.clear()
                    status_display.controls.append(ft.Text(f"未在{browser}浏览器中找到Cookie", size=16, color=ft.Colors.ORANGE))
                    page.update()
                else:
                    # 加密Cookie数据
                    encrypted_cookie_data = encrypt_data(cookie_data)
                    if encrypted_cookie_data is None:
                        status_display.controls.clear()
                        status_display.controls.append(ft.Text("Cookie加密失败", size=16, color=ft.Colors.RED))
                        page.update()
                        return

            except Exception as ex:
                status_display.controls.clear()
                status_display.controls.append(ft.Text(f"处理Cookie时出错: {str(ex)}", size=16, color=ft.Colors.RED))
                page.update()
                return

        # 显示准备发送的数据
        status_display.controls.clear()
        status_display.controls.append(ft.Text("准备发送请求...", size=16))
        status_display.controls.append(ft.Text(f"URL: {url}", size=14))
        status_display.controls.append(ft.Text(f"浏览器: {browser}", size=14))
        status_display.controls.append(ft.Text(f"使用Cookie: {use_cookie}", size=14))
        status_display.controls.append(ft.Text(f"回传下载: {return_download}", size=14))
        if encrypted_cookie_data:
            status_display.controls.append(ft.Text("Cookie数据已加密", size=14, color=ft.Colors.GREEN))
        page.update()

        # 发送主任务请求到远程服务
        result = send_main_task_request(url, encrypted_cookie_data, return_download)
        print(f"发送主任务请求结果: {str(result)[:500]}")  # 添加终端日志输出

        # 处理API响应
        status_display.controls.clear()
        if result["success"]:
            # 请求成功
            task_id = result["task_id"]
            status_display.controls.append(ft.Text(f"任务提交成功！", size=16, color=ft.Colors.GREEN))
            status_display.controls.append(ft.Text(f"任务ID: {task_id}", size=14))
            status_display.controls.append(ft.Text(result["message"], size=14))
            print(f"任务提交成功！任务ID: {task_id}")  # 添加终端日志输出

            # 将任务信息保存到数据库
            if db_handler.create_task(task_id, url, browser, use_cookie, return_download):
                status_display.controls.append(ft.Text("任务信息已保存到数据库", size=14, color=ft.Colors.GREEN))
            else:
                status_display.controls.append(ft.Text("任务信息保存到数据库失败", size=14, color=ft.Colors.RED))

            # 启动定时轮询任务状态
            poller = TaskStatusPoller(page, task_id, status_display, db_handler, load_history_tasks)
            # 直接传入协程函数给page.run_task
            page.run_task(poller.start_polling)
            print(f"已启动任务状态轮询，任务ID: {task_id}")  # 添加终端日志输出

            # 重新加载历史任务
            load_history_tasks()
        else:
            # 请求失败
            status_display.controls.append(ft.Text("任务提交失败！", size=16, color=ft.Colors.RED))
            status_display.controls.append(ft.Text(result["message"], size=14))
            if result["error"]:
                status_display.controls.append(ft.Text(f"错误详情: {result['error']}", size=12, color=ft.Colors.RED_300))
            print(f"任务提交失败！错误信息: {result['message']}")  # 添加终端日志输出
            if result["error"]:
                print(f"错误详情: {result['error']}")  # 添加终端日志输出

        page.update()

    submit_button = ft.ElevatedButton(
        text="提交任务",
        icon=ft.Icons.SEND,
        style=ft.ButtonStyle(
            color={
                "": ft.Colors.WHITE,
            },
            bgcolor={
                "": ft.Colors.BLUE_500,
            }
        ),
        width=150,
        on_click=on_submit_click
    )

    # 6. 任务状态显示区域
    status_display = ft.Column(
        controls=[
            ft.Text("任务状态", size=16, weight=ft.FontWeight.BOLD),
            ft.Divider(),
            ft.Text("暂无任务", color=ft.Colors.GREY)
        ],
        spacing=10,
        expand=True
    )

    status_container = ft.Container(
        content=status_display,
        padding=15,
        border=ft.border.all(1, ft.Colors.GREY_300),
        border_radius=5,
        expand=True
    )

    # 7. 历史任务列表展示区域
    history_list = ft.ListView(
        expand=True,
        spacing=10,
        auto_scroll=False,
        height=400  # 增加高度以确保任务卡片完整显示
    )

    history_container = ft.Container(
        content=history_list,
        padding=15,
        border=ft.border.all(1, ft.Colors.GREY_300),
        border_radius=5,
        expand=True
    )

    # 加载历史任务函数
    def load_history_tasks():
        """加载历史任务到界面"""
        try:
            tasks = db_handler.get_recent_tasks(100)  # 最多加载100个任务
            history_list.controls.clear()

            if not tasks:
                history_list.controls.append(ft.Text("暂无历史任务", color=ft.Colors.GREY))
            else:
                for task in tasks:
                    # 创建任务卡片
                    task_card = create_task_card(task)
                    history_list.controls.append(task_card)

            page.update()
        except Exception as e:
            print(f"加载历史任务时出错: {e}")
            history_list.controls.clear()
            history_list.controls.append(ft.Text(f"加载历史任务失败: {str(e)}", color=ft.Colors.RED))
            page.update()

    # 创建任务卡片函数
    def create_task_card(task):
        """创建任务卡片控件"""
        task_id = task["id"]
        url = task["url"]
        status = task["status"]
        progress = task["progress"]
        created_at = task["created_at"]

        # 根据状态设置颜色
        status_color = ft.Colors.GREEN if status == "completed" else \
                      ft.Colors.RED if status == "failed" else \
                      ft.Colors.BLUE

        # 提取结果预览
        result_preview = ""
        if task.get("result"):
            if isinstance(task["result"], dict):
                if "text" in task["result"]:
                    result_preview = task["result"]["text"][:50] + "..." if len(task["result"]["text"]) > 50 else task["result"]["text"]
                elif "transcription" in task["result"]:
                    result_preview = task["result"]["transcription"][:50] + "..." if len(task["result"]["transcription"]) > 50 else task["result"]["transcription"]
            else:
                result_str = str(task["result"])
                result_preview = result_str[:50] + "..." if len(result_str) > 50 else result_str
            result_uploader = task["result"].get("uploader", "未知作者")
            result_title = task["result"].get("title", "未知标题")
            result_preview = f"[{result_uploader}][{result_title}]{result_preview}"

        # 创建任务卡片
        card = ft.Card(
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text(f"任务ID: {task_id[:8]}...", size=14, weight=ft.FontWeight.BOLD),
                                ft.Text(f"状态: {status}", size=14, color=status_color)
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                        ),
                        ft.Text(f"URL: {url[:50]}{'...' if len(url) > 50 else ''}", size=12),
                        ft.Text(f"进度: {progress}", size=12),
                        ft.Text(f"结果预览: {result_preview}" if result_preview else "结果: 无", size=12, color=ft.Colors.GREY),
                        ft.Text(f"创建时间: {created_at}", size=12, color=ft.Colors.GREY),
                        ft.Row(
                            controls=[
                                ft.IconButton(
                                    icon=ft.Icons.INFO,
                                    tooltip="查看详情",
                                    on_click=lambda e, tid=task_id: show_task_details(tid)
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.CONTENT_COPY,
                                    tooltip="复制结果",
                                    on_click=lambda e, tid=task_id: copy_task_result(tid)
                                ) if status == "completed" else ft.Container(),
                                ft.IconButton(
                                    icon=ft.Icons.AUDIOTRACK,
                                    tooltip="复制音频路径",
                                    on_click=lambda e, tid=task_id: copy_audio_path_from_task(tid)
                                ) if status == "completed" and task.get("audio_file_path") else ft.Container(),
                                ft.IconButton(
                                    icon=ft.Icons.DOWNLOAD,
                                    tooltip="导出字幕",
                                    on_click=lambda e, tid=task_id: export_subtitle(tid)
                                ) if status == "completed" and task.get("result") else ft.Container(),
                                ft.IconButton(
                                    icon=ft.Icons.SETTINGS,
                                    tooltip="高级导出",
                                    on_click=lambda e, tid=task_id: show_advanced_export_dialog(tid)
                                ) if status == "completed" else ft.Container()
                            ],
                            alignment=ft.MainAxisAlignment.END
                        )
                    ],
                    spacing=5
                ),
                padding=10
            )
        )

        # 使用GestureDetector包装Card以实现点击功能
        gesture_detector = ft.GestureDetector(
            content=card,
            on_tap=lambda e, tid=task_id: select_task(tid)
        )
        return gesture_detector

    # 选中任务函数
    def select_task(task_id):
        """选中任务"""
        global selected_task_id
        selected_task_id = task_id

        # 更新所有任务卡片的视觉状态
        for control in history_list.controls:
            # 现在control是GestureDetector，我们需要访问其content（即Card）
            if hasattr(control, 'content') and hasattr(control.content, 'content'):
                container = control.content.content  # 注意这里需要多一层content访问
                # 重置所有卡片的背景色
                container.bgcolor = ft.Colors.TRANSPARENT
                container.border = None

                # 如果是选中的任务，设置高亮
                if hasattr(container, 'content') and hasattr(container.content, 'controls'):
                    # 获取任务ID（假设在第一个Text控件中）
                    first_row = container.content.controls[0]
                    if hasattr(first_row, 'controls') and len(first_row.controls) > 0:
                        task_text = first_row.controls[0]
                        if hasattr(task_text, 'value') and task_id[:8] in task_text.value:
                            container.bgcolor = ft.Colors.BLUE_50
                            container.border = ft.border.all(2, ft.Colors.BLUE_300)

        page.snack_bar = ft.SnackBar(
            content=ft.Text(f"已选中任务: {task_id[:8]}..."),
            bgcolor=ft.Colors.BLUE_500
        )
        page.snack_bar.open = True
        page.update()

    # 显示任务详情函数
    def show_task_details(task_id):
        """显示任务详情"""
        try:
            task = db_handler.get_task_by_id(task_id)
            if not task:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("未找到任务信息"),
                    bgcolor=ft.Colors.RED_500
                )
                page.snack_bar.open = True
                page.update()
                return

            # 格式化结果显示
            result_content = "无结果"
            audio_file_path = task.get('audio_file_path', '')

            if task['result']:
                if isinstance(task['result'], dict):
                    # 如果是字典，格式化显示关键信息
                    result = task['result']
                    if 'text' in result:
                        text_preview = result['text'][:500] + "..." if len(result['text']) > 500 else result['text']
                        result_content = f"识别文本: {text_preview}"
                    elif 'transcription' in result:
                        transcription_preview = result['transcription'][:500] + "..." if len(result['transcription']) > 500 else result['transcription']
                        result_content = f"转录文本: {transcription_preview}"
                    else:
                        # 格式化显示整个字典
                        formatted_result = json.dumps(result, indent=2, ensure_ascii=False)
                        result_content = formatted_result[:1000] + "..." if len(formatted_result) > 1000 else formatted_result
                else:
                    result_str = str(task['result'])
                    result_content = result_str[:1000] + "..." if len(result_str) > 1000 else result_str

            # 创建详情对话框
            controls_list = [
                ft.Text(f"URL: {task['url']}", size=14),
                ft.Text(f"浏览器: {task['browser']}", size=14),
                ft.Text(f"使用Cookie: {'是' if task['use_cookie'] else '否'}", size=14),
                ft.Text(f"回传下载: {'是' if task['return_download'] else '否'}", size=14),
                ft.Text(f"状态: {task['status']}", size=14),
                ft.Text(f"进度: {task['progress']}", size=14),
                ft.Text(f"创建时间: {task['created_at']}", size=14),
                ft.Text(f"更新时间: {task['updated_at']}", size=14),
                ft.Divider(),
                ft.Text("结果:", size=14, weight=ft.FontWeight.BOLD),
                ft.Container(
                    content=ft.Text(result_content, size=12),
                    padding=ft.padding.all(10),
                    border=ft.border.all(1, ft.Colors.GREY_300),
                    border_radius=5,
                    expand=True
                )
            ]

            # 如果有音频文件路径，添加音频文件路径显示
            if audio_file_path:
                controls_list.insert(-2, ft.Text(f"音频文件路径: {audio_file_path}", size=14))
                controls_list.insert(-2, ft.Row(
                    controls=[
                        ft.ElevatedButton(
                            "复制音频路径",
                            icon=ft.Icons.CONTENT_COPY,
                            on_click=lambda e, path=audio_file_path: copy_audio_path(path)
                        ),
                        ft.ElevatedButton(
                            "在文件资源管理器中打开",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=lambda e, path=audio_file_path: open_file_in_explorer(path)
                        )
                    ]
                ))

            dlg = ft.AlertDialog(
                title=ft.Text(f"任务详情 - {task_id}"),
                content=ft.Column(
                    controls=controls_list,
                    scroll=ft.ScrollMode.AUTO,
                    height=550,
                    width=700
                ),
                actions=[
                    ft.TextButton("关闭", on_click=lambda e: page.close(dlg)),
                    ft.TextButton("查看完整结果", on_click=lambda e, tid=task_id: show_full_result(tid)),
                    ft.TextButton("复制结果", on_click=lambda e, tid=task_id: copy_task_result(tid)),
                    ft.TextButton("导出字幕", on_click=lambda e, tid=task_id: export_subtitle(tid)) if task['status'] == "completed" else ft.Container()
                ]
            )
            page.open(dlg)
        except Exception as e:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(f"显示任务详情失败: {str(e)}"),
                bgcolor=ft.Colors.RED_500
            )
            page.snack_bar.open = True
            page.update()

    # 显示完整结果函数
    def show_full_result(task_id):
        """显示完整结果"""
        try:
            task = db_handler.get_task_by_id(task_id)
            if not task or not task['result']:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("未找到任务结果"),
                    bgcolor=ft.Colors.RED_500
                )
                page.snack_bar.open = True
                page.update()
                return

            result = task['result']
            full_text = ""

            if isinstance(result, dict):
                if 'text' in result:
                    full_text = result['text']
                elif 'transcription' in result:
                    full_text = result['transcription']
                else:
                    full_text = json.dumps(result, indent=2, ensure_ascii=False)
            else:
                full_text = str(result)

            # 创建完整结果显示对话框
            dlg = ft.AlertDialog(
                title=ft.Text(f"完整结果 - {task_id}"),
                content=ft.Column(
                    controls=[
                        ft.Container(
                            content=ft.Text(full_text, size=12, selectable=True),
                            padding=ft.padding.all(10),
                            border=ft.border.all(1, ft.Colors.GREY_300),
                            border_radius=5,
                            expand=True
                        )
                    ],
                    scroll=ft.ScrollMode.AUTO,
                    height=500,
                    width=700
                ),
                actions=[
                    ft.TextButton("关闭", on_click=lambda e: page.close(dlg)),
                    ft.TextButton("复制到剪贴板", on_click=lambda e, text=full_text: copy_full_text_to_clipboard(text))
                ]
            )
            page.open(dlg)
        except Exception as e:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(f"显示完整结果失败: {str(e)}"),
                bgcolor=ft.Colors.RED_500
            )
            page.snack_bar.open = True
            page.update()

    # 复制完整文本到剪贴板函数
    def copy_full_text_to_clipboard(text):
        """复制完整文本到剪贴板"""
        try:
            if text:
                page.set_clipboard(text)
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("完整结果已复制到剪贴板"),
                    bgcolor=ft.Colors.GREEN_500
                )
                page.snack_bar.open = True
            else:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("文本内容为空"),
                    bgcolor=ft.Colors.ORANGE_500
                )
                page.snack_bar.open = True
            page.update()
        except Exception as e:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(f"复制文本失败: {str(e)}"),
                bgcolor=ft.Colors.RED_500
            )
            page.snack_bar.open = True
            page.update()

    # 复制任务结果函数
    def copy_task_result(task_id):
        """复制任务结果"""
        try:
            task = db_handler.get_task_by_id(task_id)
            if not task or not task['result']:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("未找到任务结果"),
                    bgcolor=ft.Colors.RED_500
                )
                page.snack_bar.open = True
                page.update()
                return

            result = task['result']
            transcription = result.get('transcription', '') if isinstance(result, dict) else str(result)

            if transcription:
                page.set_clipboard(transcription)
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("结果已复制到剪贴板"),
                    bgcolor=ft.Colors.GREEN_500
                )
                page.snack_bar.open = True
            else:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("任务结果为空"),
                    bgcolor=ft.Colors.ORANGE_500
                )
                page.snack_bar.open = True
            page.update()
        except Exception as e:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(f"复制结果失败: {str(e)}"),
                bgcolor=ft.Colors.RED_500
            )
            page.snack_bar.open = True
            page.update()

    # 复制音频路径函数
    def copy_audio_path(audio_path):
        """复制音频文件路径到剪贴板"""
        try:
            if audio_path and isinstance(audio_path, str) and audio_path.strip():
                page.set_clipboard(audio_path.strip())
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("音频文件路径已复制到剪贴板"),
                    bgcolor=ft.Colors.GREEN_500
                )
                page.snack_bar.open = True
            else:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("音频文件路径为空"),
                    bgcolor=ft.Colors.ORANGE_500
                )
                page.snack_bar.open = True
            page.update()
        except Exception as e:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(f"复制音频路径失败: {str(e)}"),
                bgcolor=ft.Colors.RED_500
            )
            page.snack_bar.open = True
            page.update()

    # 从任务中复制音频路径函数
    def copy_audio_path_from_task(task_id):
        """从任务中复制音频文件路径到剪贴板"""
        try:
            task = db_handler.get_task_by_id(task_id)
            if not task:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("未找到任务信息"),
                    bgcolor=ft.Colors.RED_500
                )
                page.snack_bar.open = True
                page.update()
                return

            audio_file_path = task.get('audio_file_path', '')
            if audio_file_path and isinstance(audio_file_path, str) and audio_file_path.strip():
                page.set_clipboard(audio_file_path.strip())
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("音频文件路径已复制到剪贴板"),
                    bgcolor=ft.Colors.GREEN_500
                )
                page.snack_bar.open = True
            else:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("该任务没有音频文件路径"),
                    bgcolor=ft.Colors.ORANGE_500
                )
                page.snack_bar.open = True
            page.update()
        except Exception as e:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(f"复制音频路径失败: {str(e)}"),
                bgcolor=ft.Colors.RED_500
            )
            page.snack_bar.open = True
            page.update()

    # 在文件资源管理器中打开文件函数
    def open_file_in_explorer(file_path):
        """在文件资源管理器中打开文件所在目录并选中文件"""
        try:
            if file_path and isinstance(file_path, str) and os.path.exists(file_path):
                # Windows系统使用explorer命令
                if os.name == 'nt':  # Windows
                    os.system(f'explorer /select,"{file_path}"')
                # macOS系统使用open命令
                elif os.name == 'posix' and os.uname().sysname == 'Darwin':  # macOS
                    os.system(f'open -R "{file_path}"')
                # Linux系统使用xdg-open命令
                elif os.name == 'posix':  # Linux
                    directory = os.path.dirname(file_path)
                    os.system(f'xdg-open "{directory}"')

                page.snack_bar = ft.SnackBar(
                    content=ft.Text("已在文件资源管理器中打开文件位置"),
                    bgcolor=ft.Colors.GREEN_500
                )
                page.snack_bar.open = True
            else:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("文件路径无效或文件不存在"),
                    bgcolor=ft.Colors.ORANGE_500
                )
                page.snack_bar.open = True
            page.update()
        except Exception as e:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(f"打开文件资源管理器失败: {str(e)}"),
                bgcolor=ft.Colors.RED_500
            )
            page.snack_bar.open = True
            page.update()

    # 显示高级导出对话框函数
    def show_advanced_export_dialog(task_id):
        """显示高级导出字幕对话框"""
        try:
            task = db_handler.get_task_by_id(task_id)
            if not task or not task['result']:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("任务结果不可用，无法导出字幕"),
                    bgcolor=ft.Colors.RED_500
                )
                page.snack_bar.open = True
                page.update()
                return

            # 创建断句长度输入框
            min_length_input = ft.TextField(
                label="断句最小长度",
                hint_text="软标点断句的最小字符数",
                value="10",
                keyboard_type=ft.KeyboardType.NUMBER,
                width=200
            )

            # 创建文件名输入框
            task = db_handler.get_task_by_id(task_id)
            result = task['result']
            result_datestr = result.get("datestr", "251212")
            result_uploader = result.get("uploader", "未知作者")
            result_title = result.get("title", "未知标题")
            file_name = f"{result_datestr}_{result_uploader}_{result_title}_{task_id[:5]}.srt"
            file_name = sanitize_filename(file_name)
            filename_input = ft.TextField(
                label="文件名",
                hint_text="不包括扩展名",
                value=f"{file_name}",
                width=300
            )

            # 创建格式选择下拉框
            format_dropdown = ft.Dropdown(
                label="字幕格式",
                options=[
                    ft.dropdown.Option("SRT"),
                    ft.dropdown.Option("TXT")
                ],
                value="SRT",
                width=150
            )

            # 创建对话框内容
            dlg_content = ft.Column(
                controls=[
                    ft.Text("高级导出设置", size=16, weight=ft.FontWeight.BOLD),
                    ft.Divider(),
                    min_length_input,
                    filename_input,
                    format_dropdown
                ],
                spacing=15,
                width=250,
                height=250
            )

            # 创建对话框
            dlg = ft.AlertDialog(
                title=ft.Text("高级导出字幕"),
                content=dlg_content,
                actions=[
                    ft.TextButton("取消", on_click=lambda e: page.close(dlg)),
                    ft.TextButton("导出", on_click=lambda e: export_subtitle_advanced(
                        task_id,
                        int(min_length_input.value) if min_length_input.value.isdigit() else 10,
                        filename_input.value,
                        format_dropdown.value
                    ))
                ]
            )
            page.open(dlg)
        except Exception as e:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(f"显示高级导出对话框失败: {str(e)}"),
                bgcolor=ft.Colors.RED_500
            )
            page.snack_bar.open = True
            page.update()

    # 高级导出字幕函数
    def export_subtitle_advanced(task_id, min_length=10, filename="subtitle", format="SRT"):
        """高级导出字幕"""
        try:
            task = db_handler.get_task_by_id(task_id)
            if not task or not task['result']:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("任务结果不可用，无法导出字幕"),
                    bgcolor=ft.Colors.RED_500
                )
                page.snack_bar.open = True
                page.update()
                return

            # 获取结果数据
            result = task['result']

            # 生成SRT内容
            srt_content = generate_smart_srt(result, min_length)

            if not srt_content:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("生成字幕内容失败"),
                    bgcolor=ft.Colors.RED_500
                )
                page.snack_bar.open = True
                page.update()
                return

            # 确定文件扩展名
            extension = ".srt" if format.upper() == "SRT" else ".txt"

            # 确保下载目录存在
            download_dir = "download"
            if not os.path.exists(download_dir):
                os.makedirs(download_dir)

            # 构建完整的文件路径
            file_path = os.path.join(download_dir, f"{filename}{extension}")

            # 写入文件
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(srt_content)

            # 显示成功消息
            page.snack_bar = ft.SnackBar(
                content=ft.Text(f"字幕文件已导出: {file_path}"),
                bgcolor=ft.Colors.GREEN_500
            )
            page.snack_bar.open = True

            # 询问是否打开文件位置
            def open_folder(e):
                try:
                    if os.name == 'nt':  # Windows
                        os.system(f'explorer /select,"{file_path}"')
                    elif os.name == 'posix' and os.uname().sysname == 'Darwin':  # macOS
                        os.system(f'open -R "{file_path}"')
                    elif os.name == 'posix':  # Linux
                        directory = os.path.dirname(file_path)
                        os.system(f'xdg-open "{directory}"')
                except Exception as ex:
                    print(f"打开文件位置时出错: {ex}")
                finally:
                    page.close(confirm_dlg)

            def close_dialog(e):
                page.close(confirm_dlg)

            confirm_dlg = ft.AlertDialog(
                title=ft.Text("导出成功"),
                content=ft.Text(f"字幕文件已导出到:\n{file_path}\n\n是否要打开文件所在位置?"),
                actions=[
                    ft.TextButton("否", on_click=close_dialog),
                    ft.TextButton("是", on_click=open_folder)
                ]
            )
            page.open(confirm_dlg)
            page.update()
        except Exception as e:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(f"导出字幕失败: {str(e)}"),
                bgcolor=ft.Colors.RED_500
            )
            page.snack_bar.open = True
            page.update()

    # 导出字幕函数
    def export_subtitle(task_id):
        """导出字幕"""
        try:
            print(f"开始导出字幕，任务ID: {task_id}")  # 添加调试信息
            task = db_handler.get_task_by_id(task_id)
            if not task or not task['result']:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("任务结果不可用，无法导出字幕"),
                    bgcolor=ft.Colors.RED_500
                )
                page.snack_bar.open = True
                page.update()
                print(f"任务结果不可用，任务ID: {task_id}")  # 添加调试信息
                return

            # 获取结果数据
            result = task['result']
            result_dbg = result.get('transcription',"")[:100]
            print(f"获取到的结果数据: {result_dbg}")  # 添加调试信息

            # 生成SRT内容
            srt_content = generate_smart_srt(result)
            print(f"生成的SRT内容长度: {len(srt_content)}")  # 添加调试信息

            if not srt_content:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("生成字幕内容失败"),
                    bgcolor=ft.Colors.RED_500
                )
                page.snack_bar.open = True
                page.update()
                print("生成字幕内容失败")  # 添加调试信息
                return

            # 确保下载目录存在
            download_dir = "download"
            if not os.path.exists(download_dir):
                os.makedirs(download_dir)
                print(f"创建下载目录: {download_dir}")  # 添加调试信息

            # 构建完整的文件路径
            result_datestr = result.get("datestr", "251212")
            result_uploader = result.get("uploader", "未知作者")
            result_title = result.get("title", "未知标题")
            file_name = f"{result_datestr}_{result_uploader}_{result_title}_{task_id[:5]}.srt"
            file_name = sanitize_filename(file_name)
            file_path = os.path.join(download_dir, file_name)
            print(f"字幕文件路径: {file_path}")  # 添加调试信息

            # 写入文件
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(srt_content)
            print(f"字幕文件已写入: {file_path}")  # 添加调试信息

            # 显示成功消息
            page.snack_bar = ft.SnackBar(
                content=ft.Text(f"字幕文件已导出: {file_path}"),
                bgcolor=ft.Colors.GREEN_500
            )
            page.snack_bar.open = True

            # 询问是否打开文件位置
            def open_folder(e):
                try:
                    if os.name == 'nt':  # Windows
                        os.system(f'explorer /select,"{file_path}"')
                    elif os.name == 'posix' and os.uname().sysname == 'Darwin':  # macOS
                        os.system(f'open -R "{file_path}"')
                    elif os.name == 'posix':  # Linux
                        directory = os.path.dirname(file_path)
                        os.system(f'xdg-open "{directory}"')
                except Exception as ex:
                    print(f"打开文件位置时出错: {ex}")
                finally:
                    page.close(confirm_dlg)

            def close_dialog(e):
                page.close(confirm_dlg)

            confirm_dlg = ft.AlertDialog(
                title=ft.Text("导出成功"),
                content=ft.Text(f"字幕文件已导出到:\n{file_path}\n\n是否要打开文件所在位置?"),
                actions=[
                    ft.TextButton("否", on_click=close_dialog),
                    ft.TextButton("是", on_click=open_folder)
                ]
            )
            page.open(confirm_dlg)
            page.update()
            print(f"字幕导出成功: {file_path}")  # 添加调试信息
        except Exception as e:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(f"导出字幕失败: {str(e)}"),
                bgcolor=ft.Colors.RED_500
            )
            page.snack_bar.open = True
            page.update()
            print(f"导出字幕失败: {str(e)}")  # 添加调试信息
            traceback.print_exc()  # 添加详细的错误追踪

    # 页面布局
    # 顶部输入区域
    input_row = ft.Row(
        controls=[
            url_input,
            browser_dropdown
        ],
        spacing=10,
        expand=True
    )

    option_row = ft.Row(
        controls=[
            cookie_checkbox,
            download_checkbox,
            submit_button
        ],
        spacing=20,
        alignment=ft.MainAxisAlignment.START
    )

    top_section = ft.Column(
        controls=[
            input_row,
            option_row
        ],
        spacing=15
    )

    # 中间状态显示区域
    middle_section = ft.Row(
        controls=[
            ft.Column(
                controls=[status_container],
                expand=True
            )
        ],
        expand=False,
        height=150  # 增加高度以提供更多显示空间
    )

    # 底部历史任务和结果操作区域
    bottom_section = ft.Row(
        controls=[
            ft.Column(
                controls=[
                    ft.Text("历史任务", size=16, weight=ft.FontWeight.BOLD),
                    ft.Divider(),
                    history_container
                ],
                expand=1
            ),
            # ft.Column(
            #     controls=[result_container],
            #     width=300
            # )
        ],
        spacing=15,
        expand=True
    )

    # 主布局
    main_layout = ft.Column(
        controls=[
            # ft.Text("Video to Text Converter", size=24, weight=ft.FontWeight.BOLD),
            top_section,
            middle_section,
            bottom_section
        ],
        spacing=20,
        expand=True
    )

    # 设置页面内容
    page.add(main_layout)

    # 加载历史任务
    load_history_tasks()

if __name__ == "__main__":
    ft.app(target=main)