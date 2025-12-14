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
import platform
from pathvalidate import sanitize_filename
from datetime import datetime
from collections.abc import Mapping
from db_handler import DatabaseHandler
from audio_downloader import download_audio_file, cleanup_remote_audio
from crypto_utils import encrypt_data
from srt_utils import generate_smart_srt, is_mainly_cjk

# 设置设置环境变量以及默认编码UTF-8
if sys.version_info[0] == 3 and sys.version_info[1] >= 7:
    # 对于Python 3.7及以上版本
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)
sys.stdout.reconfigure(line_buffering=True)
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['NO_PROXY'] = '.local,127.0.0.1,localhost'

# 加载配置文件
def load_config():
    """加载配置文件"""
    config_path = os.path.join(os.path.dirname(__file__), 'settings.json')

    # 默认配置
    default_config = {
        "server": {
            "ip": "tkmini.local",
            "port": 5001
        },
        "paths": {
            "download_dir": "download",
            "db_dir": "."
        }
    }

    # 如果配置文件不存在，创建默认配置文件
    if not os.path.exists(config_path):
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, ensure_ascii=False, indent=4)
        return default_config

    # 读取配置文件
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # 用默认配置填充缺失的项
        for section, values in default_config.items():
            if section not in config:
                config[section] = values
            elif isinstance(values, dict):
                for key, value in values.items():
                    if key not in config[section]:
                        config[section][key] = value
        return config
    except Exception as e:
        print(f"加载配置文件失败: {e}，使用默认配置")
        return default_config

# 全局配置变量
CONFIG = load_config()

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
    # 使用配置中的db_dir，并确保路径兼容性
    db_dir = CONFIG["paths"]["db_dir"]
    db_dir = os.path.normpath(db_dir)
    db_handler = DatabaseHandler(db_path=db_dir)
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
        # 从配置中获取服务器IP和端口
        ip = CONFIG["server"]["ip"]
        port = CONFIG["server"]["port"]

        # 构造API请求URL
        api_url = f"http://{ip}:{port}/api/process"

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
        print(f"开始轮询任务状态，任务ID: {self.task_id}")
        loop = asyncio.get_event_loop()
        # 从配置中获取服务器IP和端口
        ip = CONFIG["server"]["ip"]
        port = CONFIG["server"]["port"]
        while self.is_polling:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"http://{ip}:{port}/api/status/{self.task_id}", timeout=30) as response:
                        print(f"收到状态响应，状态码: {response.status}")
                        if response.status == 200:
                            result = await response.json()
                            print(f"解析到的响应数据: {str(result)[:200]}")
                            await self.update_ui_with_result(result)

                            # 如果任务已完成或失败，停止轮询
                            if result.get("status") in ["completed", "failed"]:
                                self.is_polling = False
                                print(f"任务已完成或失败，停止轮询，最终状态: {result.get('status')}")
                                break
                        else:
                            # 处理HTTP错误，确保错误消息可以正确编码
                            error_msg = f"HTTP错误 {response.status}"
                            await self.update_status_display(error_msg, ft.Colors.RED)
                            # 确保传递给数据库的错误消息是可编码的
                            safe_error_msg = error_msg.encode('utf-8', errors='ignore').decode('utf-8')
                            await loop.run_in_executor(None, self.db_handler.save_task_error, self.task_id, safe_error_msg)
                            self.is_polling = False
                            print(f"轮询过程中发生HTTP错误: {error_msg}")
                            break
            except Exception as e:
                error_msg = f"轮询错误: {str(e)}"
                await self.update_status_display(error_msg, ft.Colors.RED)
                safe_error_msg = error_msg.encode('utf-8', errors='ignore').decode('utf-8')
                await loop.run_in_executor(None, self.db_handler.save_task_error, self.task_id, safe_error_msg)
                self.is_polling = False
                print(f"轮询错误: {error_msg}")
                break

            # 等待2秒后再次轮询
            await asyncio.sleep(2)

    async def update_ui_with_result(self, result):
        """更新UI界面和数据库"""
        old_status = self.db_handler.get_task_by_id(self.task_id).get('status', 'unknown')
        task_status = result.get("status", "unknown")
        task_progress = result.get("progress", "未知进度")
        print(f"收到任务状态更新: 状态={task_status}, 进度={task_progress}")

        # 确保进度信息是字符串并且可以正确编码
        if not isinstance(task_progress, str):
            task_progress = str(task_progress)

        # 根据任务状态设置颜色
        status_color = ft.Colors.GREEN if task_status == "completed" else \
                      ft.Colors.RED if task_status == "failed" else \
                      ft.Colors.BLUE

        # 更新UI状态显示
        self.status_display.controls.clear()
        self.status_display.controls.extend([ft.Text(f"任务状态: {task_status}", size=16, color=status_color),
            ft.Text(f"进度: {task_progress}", size=11)])

        # 如果有额外信息，也显示出来
        if "message" in result:
            message = result['message']
            if not isinstance(message, str):
                message = str(message)
            self.status_display.controls.append(ft.Text(f"信息: {message}", size=11))

        self.status_display.update()

        # 更新数据库状态
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.db_handler.update_task_status, self.task_id, task_status, task_progress)

        # 如果任务已完成，处理结果
        if task_status == "completed":
            if "result" in result and isinstance(result["result"], Mapping):
                now = datetime.now()
                result["result"]["datestr"] = f"{now:%y%m%d}"
            await self.save_result_to_db(result, loop)

        should_refresh_history = task_status in ["completed", "failed"]

        # 刷新历史任务列表以更新状态显示
        if old_status != task_status and should_refresh_history and hasattr(self, 'load_history_tasks') and self.load_history_tasks:
            self.load_history_tasks()

    async def update_status_display(self, message, color=ft.Colors.BLACK):
        """更新状态显示"""
        # 确保消息是字符串并且可以正确编码
        if not isinstance(message, str):
            message = str(message)

        self.status_display.controls.clear()
        self.status_display.controls.append(ft.Text(message, size=11, color=color))
        self.page.update()
        print(f"状态更新: {message}")  # 添加终端日志输出

    async def save_result_to_db(self, result, loop):
        """保存任务结果到数据库"""
        try:
            # 保存结果到数据库
            await loop.run_in_executor(None, self.db_handler.save_task_result, self.task_id, result.get("result", {}))
            self.status_display.controls.append(ft.Text("结果已保存到数据库", size=11, color=ft.Colors.GREEN))
            self.status_display.update()

            # 如果需要下载音频且结果中有音频URL，则下载音频
            if result.get("result", {}).get("audio_url"):
                audio_url = result["result"]["audio_url"]
                result_datestr = result["result"].get("datestr", "251212")
                result_uploader = result["result"].get("uploader", "未知作者")
                result_title = result["result"].get("title", "未知标题")
                # 从配置中获取下载目录和服务器信息
                download_dir = CONFIG["paths"]["download_dir"]
                ip = CONFIG["server"]["ip"]
                port = CONFIG["server"]["port"]

                # 下载音频文件
                audio_file_path = await loop.run_in_executor(None, download_audio_file, self.task_id, audio_url, self.db_handler, download_dir, ip, port, result_datestr, result_uploader, result_title)
                if audio_file_path:
                    self.status_display.controls.append(ft.Text(f"音频文件已下载: {audio_file_path}", size=11, color=ft.Colors.GREEN))

                    # 清理远程音频文件
                    clean_state = await loop.run_in_executor(None, cleanup_remote_audio, self.task_id, ip, port)
                    if clean_state:
                        self.status_display.controls.append(ft.Text("远程音频文件已清理", size=11, color=ft.Colors.GREEN))
                    else:
                        self.status_display.controls.append(ft.Text("远程音频文件清理失败", size=11, color=ft.Colors.ORANGE))
                else:
                    self.status_display.controls.append(ft.Text("音频文件下载失败", size=11, color=ft.Colors.RED))

            self.status_display.update()
        except Exception as e:
            error_msg = f"保存结果时出错: {str(e)}"
            self.status_display.controls.append(ft.Text(error_msg, size=11, color=ft.Colors.RED))
            self.status_display.update()
            await loop.run_in_executor(None, self.db_handler.save_task_error, self.task_id, error_msg)

def main(page: ft.Page):
    global selected_task_id
    selected_task_id = None

    # 页面基本设置
    page.title = "Video2Text 一键视频语音识别"
    page.window.width = 1200
    page.window.height = 800
    page.window.min_width = 800
    page.window.min_height = 600
    system_name = platform.system()
    if system_name == "Windows":
        font_name = "Microsoft YaHei UI"
    elif system_name == "Darwin": # macOS
        font_name = "PingFang SC"
    else:
        font_name = "sans-serif" # Linux 或其他
    page.theme = ft.Theme(font_family=font_name)
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
        submit_button.disabled = True
        submit_button.text = "提交中..."
        submit_button.update() 
        try:
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
            status_display.update()
            # 获取Cookie（如果需要）
            encrypted_cookie_data = None
            if use_cookie:
                try:
                    # 获取浏览器Cookie
                    cookie_data = get_cookies_via_rookie(browser)
                    if cookie_data is None:
                        status_display.controls.clear()
                        status_display.controls.append(ft.Text(f"获取{browser}浏览器Cookie失败", size=16, color=ft.Colors.RED))
                        status_display.update()
                        return
                    if not cookie_data:
                        status_display.controls.clear()
                        status_display.controls.append(ft.Text(f"未在{browser}浏览器中找到Cookie", size=16, color=ft.Colors.ORANGE))
                        status_display.update()
                    else:
                        # 加密Cookie数据
                        encrypted_cookie_data = encrypt_data(cookie_data)
                        if encrypted_cookie_data is None:
                            status_display.controls.clear()
                            status_display.controls.append(ft.Text("Cookie加密失败", size=16, color=ft.Colors.RED))
                            status_display.update()
                            return
                except Exception as ex:
                    status_display.controls.clear()
                    status_display.controls.append(ft.Text(f"处理Cookie时出错: {str(ex)}", size=16, color=ft.Colors.RED))
                    status_display.update()
                    return
            # 显示准备发送的数据
            status_display.controls.clear()
            status_display.controls.append(ft.Text("准备发送请求...", size=16))
            status_display.controls.append(ft.Text(f"URL: {url}\n浏览器: {browser}\n使用Cookie: {use_cookie}\n回传下载: {return_download}", size=11))
            if encrypted_cookie_data:
                status_display.controls.append(ft.Text("Cookie数据已加密", size=11, color=ft.Colors.GREEN))
            status_display.update()
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
                url_input.value = ""
                url_input.update()
            else:
                # 请求失败
                status_display.controls.append(ft.Text("任务提交失败！", size=16, color=ft.Colors.RED))
                status_display.controls.append(ft.Text(result["message"], size=14))
                if result["error"]:
                    status_display.controls.append(ft.Text(f"错误详情: {result['error']}", size=12, color=ft.Colors.RED_300))
                print(f"任务提交失败！错误信息: {result['message']}")  # 添加终端日志输出
                if result["error"]:
                    print(f"错误详情: {result['error']}")  # 添加终端日志输出
            status_display.update()
        except Exception as e:
            # 捕获所有未预料的异常，防止按钮永远卡在“提交中”
            print(f"提交过程发生未知错误: {e}")
            page.snack_bar = ft.SnackBar(content=ft.Text(f"发生错误: {e}"), bgcolor=ft.Colors.RED)
            page.snack_bar.open = True
            page.update()
        finally:
            submit_button.disabled = False
            submit_button.text = "提交任务"
            submit_button.update()

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
            ft.Text("任务状态", size=14, weight=ft.FontWeight.BOLD),
            # ft.Divider(),
            ft.Text("暂无任务", color=ft.Colors.GREY)
        ],
        spacing=10,
        expand=True,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
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
    def load_history_tasks(clear=False):
        """加载历史任务到界面"""
        try:
            tasks = db_handler.get_recent_tasks(100)  # 最多加载100个任务

            if clear:
                # 将非completed状态的任务标记为failed
                for task in tasks:
                    if task["status"] not in ["completed"]:
                        db_handler.update_task_status(task["id"], "failed", "任务被中断")
                # 重新获取更新后的任务列表
                tasks = db_handler.get_recent_tasks(100)

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
                    result_preview = task["result"]["transcription"][:320] + "..." if len(task["result"]["transcription"]) > 320 else task["result"]["transcription"]
            else:
                result_str = str(task["result"])
                result_preview = result_str[:200] + "..." if len(result_str) > 200 else result_str
            result_uploader = task["result"].get("uploader", "未知作者")
            result_title = task["result"].get("title", "未知标题")
            result_title = result_title[:60] + "..." if len(result_title) > 60 else result_title
            result_coockie_status = task["result"].get("cookie_status", 0)
            if result_coockie_status == 0:
                result_coockie = "⬜"
            elif result_coockie_status == 1:
                result_coockie = "🍪"
            else:
                result_coockie = "⛔"
            result_preview = f"{result_coockie} 🧑{result_uploader} ✍️{result_title} ➡️{result_preview}"

        # 左侧信息栏
        left_column = ft.Column(
            controls=[
                ft.Text(f"URL: {url[:55]}{'...' if len(url) > 55 else ''}, ID: {task_id[:10]}...", size=14, selectable=True, weight=ft.FontWeight.BOLD),
                ft.Text(f" {result_preview}" if result_preview else "结果: 无", size=12, color=ft.Colors.GREY, max_lines=4, overflow=ft.TextOverflow.ELLIPSIS),
            ],
            spacing=5,
            expand=True # 让左栏撑满可用空间
        )

        # 右侧状态与操作栏
        right_column = ft.Column(
            controls=[
                ft.Text(f"状态: {status}", size=14, color=status_color, weight=ft.FontWeight.BOLD),
                ft.Text(f"{created_at}", size=12, color=ft.Colors.GREY),
                ft.Row(
                    controls=[
                        ft.IconButton(icon=ft.Icons.DELETE, tooltip="删除条目", on_click=lambda e, tid=task_id: delete_task_entry(tid, history_list, db_handler), icon_color=ft.Colors.RED_300) if status in ["completed", "failed"] else ft.Container(),
                        ft.IconButton(icon=ft.Icons.DOWNLOAD, tooltip="导出字幕", on_click=lambda e, tid=task_id: export_subtitle(tid)) if status == "completed" and task.get("result") else ft.Container(),
                        ft.IconButton(icon=ft.Icons.INFO, tooltip="查看详情", on_click=lambda e, tid=task_id: show_task_details(tid)),
                        ft.IconButton(icon=ft.Icons.CONTENT_COPY, tooltip="复制结果", on_click=lambda e, tid=task_id: copy_task_result(tid)) if status == "completed" else ft.Container(),
                        ft.IconButton(icon=ft.Icons.SETTINGS, tooltip="高级导出", on_click=lambda e, tid=task_id: show_interactive_editor_dialog(page, tid, db_handler)) if status == "completed" else ft.Container(),
                    ],
                    spacing=0, # 按钮间距调小
                    alignment=ft.MainAxisAlignment.END,
                )
            ],
            spacing=5,
            # 【关键】让右栏内容右上对齐
            alignment=ft.MainAxisAlignment.START,
            horizontal_alignment=ft.CrossAxisAlignment.END,
            width=250 # 给右栏一个固定宽度
        )
        # 组合左右两栏
        card_content = ft.Row(
            controls=[
                left_column,
                right_column
            ],
            vertical_alignment=ft.CrossAxisAlignment.START, # 顶部对齐
            spacing=20
        )
        # 创建最终的卡片
        card = ft.Card(
            content=ft.Container(
                content=card_content,
                padding=15
            )
        )
        # 使用GestureDetector包装Card以实现点击功能
        gesture_detector = ft.GestureDetector(
            content=card,
            on_tap=lambda e, tid=task_id: select_task(tid)
        )
        # 将任务ID存储在gesture_detector中，方便后续查找
        gesture_detector.task_id = task_id
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

    # 删除任务条目函数
    def delete_task_entry(task_id, history_list, db_handler):
        """从数据库和列表中删除任务条目"""
        print(f"Attempting to delete task: {task_id}")  # 调试信息
        try:
            # 从数据库中删除任务
            if db_handler.delete_task(task_id):
                print(f"Task {task_id} deleted from database")  # 调试信息
                # 从UI列表中移除任务卡片
                removed = False
                for i in range(len(history_list.controls) - 1, -1, -1):  # 逆序遍历避免索引问题
                    control = history_list.controls[i]
                    # 检查控件是否有task_id属性
                    if hasattr(control, 'task_id') and control.task_id == task_id:
                        history_list.controls.pop(i)
                        print(f"Task {task_id} removed from UI at index {i}")  # 调试信息
                        removed = True
                        break

                if not removed:
                    print(f"Task {task_id} not found in UI controls")  # 调试信息

                history_list.update()
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("任务条目已删除"),
                    bgcolor=ft.Colors.GREEN_500
                )
            else:
                print(f"Failed to delete task {task_id} from database")  # 调试信息
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("删除任务条目失败"),
                    bgcolor=ft.Colors.RED_500
                )
            page.snack_bar.open = True
            page.update()
        except Exception as e:
            print(f"Exception in delete_task_entry: {e}")  # 调试信息
            import traceback
            traceback.print_exc()  # 打印完整的错误堆栈
            page.snack_bar = ft.SnackBar(
                content=ft.Text(f"删除任务条目时出错: {str(e)}"),
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
            
    def show_interactive_editor_dialog(page: ft.Page, task_id, db_handler):
        """
        显示交互式字幕编辑器对话框
        """
        # 1. 获取数据
        task = db_handler.get_task_by_id(task_id)
        if not task or not task['result']:
            page.snack_bar = ft.SnackBar(content=ft.Text("数据不可用"), bgcolor=ft.Colors.RED)
            page.snack_bar.open = True
            page.update()
            return
        
        raw_result = task['result']
        
        # 2. 准备初始状态
        # 默认文件名生成
        result_datestr = raw_result.get("datestr", "251212")
        result_uploader = raw_result.get("uploader", "未知作者")
        result_title = raw_result.get("title", "未知标题")
        default_filename = f"{result_datestr}_{result_uploader}_{result_title}_{task_id[:5]}"
        default_filename = sanitize_filename(default_filename)
        
        # 3. 定义 UI 控件 (Controls)
        
        # A. 字幕预览编辑器 (核心组件)
        editor_field = ft.TextField(
            value="", # 初始为空，稍后通过 slider 初始化
            multiline=True,
            min_lines=15,
            max_lines=15,
            text_size=14,
            text_style=ft.TextStyle(font_family="Consolas, monospace"), # 等宽字体方便看时间轴
            border_color=ft.Colors.OUTLINE,
            expand=True
        )
        
        # B. 滑块状态显示文本
        min_length_default = 15 if is_mainly_cjk(raw_result.get("transcription", "缺省内容")) else 40
        slider_label = ft.Text(f"当前断句阈值: {min_length_default} 字")
        
        # C. 滑块事件处理函数
        def on_slider_change(e):
            min_len = int(e.control.value)
            slider_label.value = f"当前断句阈值: {min_len} 字"
            
            # 核心：重新计算 SRT 内容并填入编辑器
            # 注意：这里我们假设用户还在调整滑块，所以会覆盖手动编辑的内容。
            # 如果你想做得更高级，可以加个锁或者提示，但这是最还原 Streamlit 的做法。
            new_content = generate_smart_srt(raw_result, min_length=min_len)
            editor_field.value = new_content
            editor_field.update()
            slider_label.update()

        # D. 滑块组件
        length_slider = ft.Slider(
            min=8, max=80, divisions=45, value=min_length_default,
            label="{value}",
            on_change=on_slider_change
        )
        
        # E. 底部文件名和保存按钮
        filename_input = ft.TextField(
            label="文件名 (无需后缀)", 
            value=default_filename, 
            expand=True,
            height=40,
            text_size=12, 
            label_style=ft.TextStyle(size=13),
            content_padding=ft.padding.only(left=10, right=10, bottom=10),
        )
        
        # F. 保存函数
        def save_subtitle(e):
            try:
                # 获取当前编辑器里的内容（包含用户刚才可能的手动修改）
                final_content = editor_field.value
                fname = filename_input.value
                
                download_dir = "download"
                if not os.path.exists(download_dir):
                    os.makedirs(download_dir)
                
                full_path = os.path.join(download_dir, f"{fname}.srt")
                
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(final_content)
                
                page.close(dlg) # 关闭对话框
                
                # 成功提示弹窗
                def open_folder(_):
                    folder_path = os.path.abspath(download_dir)
                    if os.name == 'nt': os.system(f'explorer "{folder_path}"')
                    elif os.name == 'posix': os.system(f'xdg-open "{folder_path}"')
                    page.close(success_dlg)

                success_dlg = ft.AlertDialog(
                    title=ft.Text("导出成功"),
                    content=ft.Text(f"文件已保存至:\n{full_path}"),
                    actions=[
                        ft.TextButton("打开文件夹", on_click=open_folder),
                        ft.TextButton("关闭", on_click=lambda _: page.close(success_dlg))
                    ]
                )
                page.open(success_dlg)
                
            except Exception as ex:
                page.snack_bar = ft.SnackBar(content=ft.Text(f"保存失败: {ex}"), bgcolor=ft.Colors.RED)
                page.snack_bar.open = True
                page.update()

        # 4. 组装对话框内容
        
        # 初始化一次内容
        initial_content = generate_smart_srt(raw_result, min_length=min_length_default)
        editor_field.value = initial_content

        dlg_content = ft.Column(
            controls=[
                # ft.Text("智能断句调整", size=16, weight=ft.FontWeight.BOLD),
                ft.Container(
                    content=ft.Column([
                        slider_label,
                        length_slider,
                        ft.Text("💡 提示：向右拖动可合并短句，编辑器支持直接修改文字。", size=12, color=ft.Colors.GREY)
                    ]),
                    bgcolor=ft.Colors.WHITE,
                    padding=10,
                    border_radius=5
                ),
                editor_field, # 中间的大编辑器
                ft.Divider(),
                ft.Row([
                    filename_input,
                    ft.ElevatedButton(
                        "保存 SRT", 
                        icon=ft.Icons.SAVE, 
                        on_click=save_subtitle,
                        style=ft.ButtonStyle(bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
                    )
                ])
            ],
            width=900, # 设置得宽一点
            height=600, # 设置得高一点
            scroll=ft.ScrollMode.AUTO
        )

        dlg = ft.AlertDialog(
            title=ft.Text("字幕编辑器"),
            content=dlg_content,
            actions=[
                ft.TextButton("关闭", on_click=lambda e: page.close(dlg))
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        page.open(dlg)

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
            result_dbg = result.get('transcription',"")[:500]
            min_length_default = 15 if is_mainly_cjk(result_dbg) else 40

            # 生成SRT内容
            srt_content = generate_smart_srt(result, min_length_default)
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
        # expand=False,
        height=150  # 增加高度以提供更多显示空间
    )

    # 底部历史任务和结果操作区域
    bottom_section = ft.Row(
        controls=[
            ft.Column(
                controls=[
                    # ft.Text("历史任务", size=16, weight=ft.FontWeight.BOLD),
                    # ft.Divider(),
                    history_container
                ],
                expand=1
            ),
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
    load_history_tasks(clear=True)

if __name__ == "__main__":
    ft.app(target=main)