"""
数据库处理模块
提供数据库初始化、任务管理、结果存储等功能
"""

import sqlite3
import json
import os
from typing import Dict, Any, Optional, List
from datetime import datetime


class DatabaseHandler:
    """处理数据库操作的类"""

    def __init__(self, db_path: str = "task.db"):
        """
        初始化数据库处理器

        Args:
            db_path (str): 数据库文件路径
        """
        # 规范化数据库路径以确保跨平台兼容性
        self.db_path = os.path.normpath(db_path)
        # 确保数据库连接使用UTF-8编码
        self.init_db()

    def init_db(self):
        """初始化数据库表结构"""
        # 使用UTF-8编码连接数据库
        conn = sqlite3.connect(self.db_path)
        # 设置文本工厂以确保UTF-8编码
        conn.text_factory = lambda x: str(x, 'utf-8', 'ignore') if isinstance(x, bytes) else str(x)
        cursor = conn.cursor()
        
        # 创建任务表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                url TEXT,
                browser TEXT,
                use_cookie BOOLEAN,
                return_download BOOLEAN,
                status TEXT,
                progress TEXT,
                result TEXT,  -- 存储JSON格式的结果
                audio_file_path TEXT,  -- 音频文件路径
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 创建索引以提高查询性能
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC)
        """)
        
        conn.commit()
        conn.close()

    def create_task(self, task_id: str, url: str, browser: str,
                   use_cookie: bool, return_download: bool) -> bool:
        """
        创建新任务记录

        Args:
            task_id (str): 任务ID
            url (str): 视频URL
            browser (str): 浏览器类型
            use_cookie (bool): 是否使用Cookie
            return_download (bool): 是否回传下载

        Returns:
            bool: 是否成功创建
        """
        try:
            # 使用UTF-8编码连接数据库
            conn = sqlite3.connect(self.db_path)
            conn.text_factory = lambda x: str(x, 'utf-8', 'ignore') if isinstance(x, bytes) else str(x)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO tasks (id, url, browser, use_cookie, return_download, status, progress)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (task_id, url, browser, use_cookie, return_download, "submitted", "任务已提交"))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"创建任务记录时出错: {e}")
            return False

    def update_task_status(self, task_id: str, status: str, progress: str = None) -> bool:
        """
        更新任务状态

        Args:
            task_id (str): 任务ID
            status (str): 任务状态
            progress (str, optional): 任务进度描述

        Returns:
            bool: 是否成功更新
        """
        try:
            # 使用UTF-8编码连接数据库
            conn = sqlite3.connect(self.db_path)
            conn.text_factory = lambda x: str(x, 'utf-8', 'ignore') if isinstance(x, bytes) else str(x)
            cursor = conn.cursor()

            # 确保progress是字符串并且可以正确编码
            if progress is not None and not isinstance(progress, str):
                progress = str(progress)

            if progress is not None:
                cursor.execute("""
                    UPDATE tasks
                    SET status = ?, progress = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (status, progress, task_id))
            else:
                cursor.execute("""
                    UPDATE tasks
                    SET status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (status, task_id))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"更新任务状态时出错: {e}")
            return False

    def save_task_result(self, task_id: str, result: Dict[str, Any],
                        audio_file_path: str = None) -> bool:
        """
        保存任务结果

        Args:
            task_id (str): 任务ID
            result (dict): 任务结果数据
            audio_file_path (str, optional): 音频文件路径

        Returns:
            bool: 是否成功保存
        """
        try:
            # 使用UTF-8编码连接数据库
            conn = sqlite3.connect(self.db_path)
            conn.text_factory = lambda x: str(x, 'utf-8', 'ignore') if isinstance(x, bytes) else str(x)
            cursor = conn.cursor()

            # 将结果转换为JSON字符串存储，确保使用UTF-8编码
            result_json = json.dumps(result, ensure_ascii=False, separators=(',', ':'))

            cursor.execute("""
                UPDATE tasks
                SET status = ?, progress = ?, result = ?, audio_file_path = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, ("completed", "处理完成", result_json, audio_file_path, task_id))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"保存任务结果时出错: {e}")
            return False

    def save_task_error(self, task_id: str, error_message: str) -> bool:
        """
        保存任务错误信息

        Args:
            task_id (str): 任务ID
            error_message (str): 错误信息

        Returns:
            bool: 是否成功保存
        """
        try:
            # 确保错误消息是字符串并且可以正确编码
            if not isinstance(error_message, str):
                error_message = str(error_message)

            # 使用UTF-8编码连接数据库
            conn = sqlite3.connect(self.db_path)
            conn.text_factory = lambda x: str(x, 'utf-8', 'ignore') if isinstance(x, bytes) else str(x)
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE tasks
                SET status = ?, progress = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, ("failed", error_message, task_id))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"保存任务错误时出错: {e}")
            return False

    def delete_task(self, task_id: str) -> bool:
        """
        删除任务记录

        Args:
            task_id (str): 任务ID

        Returns:
            bool: 是否成功删除
        """
        try:
            # 使用UTF-8编码连接数据库
            conn = sqlite3.connect(self.db_path)
            conn.text_factory = lambda x: str(x, 'utf-8', 'ignore') if isinstance(x, bytes) else str(x)
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM tasks WHERE id = ?
            """, (task_id,))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"删除任务时出错: {e}")
            return False

    def get_task_by_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        根据任务ID获取任务信息

        Args:
            task_id (str): 任务ID

        Returns:
            dict: 任务信息，如果未找到返回None
        """
        try:
            # 使用UTF-8编码连接数据库
            conn = sqlite3.connect(self.db_path)
            conn.text_factory = lambda x: str(x, 'utf-8', 'ignore') if isinstance(x, bytes) else str(x)
            conn.row_factory = sqlite3.Row  # 使结果可以通过列名访问
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM tasks WHERE id = ?
            """, (task_id,))

            row = cursor.fetchone()
            conn.close()

            if row:
                # 将Row对象转换为字典
                task_dict = dict(row)
                # 解析JSON结果
                if task_dict["result"]:
                    try:
                        task_dict["result"] = json.loads(task_dict["result"])
                    except json.JSONDecodeError:
                        pass  # 如果解析失败，保持原样
                return task_dict
            return None
        except Exception as e:
            print(f"获取任务信息时出错: {e}")
            return None

    def get_recent_tasks(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取最近的任务列表

        Args:
            limit (int): 最大返回数量

        Returns:
            list: 任务列表
        """
        try:
            # 使用UTF-8编码连接数据库
            conn = sqlite3.connect(self.db_path)
            conn.text_factory = lambda x: str(x, 'utf-8', 'ignore') if isinstance(x, bytes) else str(x)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?
            """, (limit,))

            rows = cursor.fetchall()
            conn.close()

            tasks = []
            for row in rows:
                task_dict = dict(row)
                # 解析JSON结果
                if task_dict["result"]:
                    try:
                        task_dict["result"] = json.loads(task_dict["result"])
                    except json.JSONDecodeError:
                        pass  # 如果解析失败，保持原样
                tasks.append(task_dict)

            return tasks
        except Exception as e:
            print(f"获取任务列表时出错: {e}")
            return []

    def delete_old_tasks(self, days: int = 30) -> int:
        """
        删除指定天数之前的旧任务

        Args:
            days (int): 保留天数

        Returns:
            int: 删除的任务数量
        """
        try:
            # 使用UTF-8编码连接数据库
            conn = sqlite3.connect(self.db_path)
            conn.text_factory = lambda x: str(x, 'utf-8', 'ignore') if isinstance(x, bytes) else str(x)
            cursor = conn.cursor()

            # 计算删除截止日期
            cutoff_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute("""
                DELETE FROM tasks
                WHERE created_at < datetime('now', '-{} days')
            """.format(days))

            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()

            return deleted_count
        except Exception as e:
            print(f"删除旧任务时出错: {e}")
            return 0


# 使用示例
if __name__ == "__main__":
    # 创建数据库处理器实例
    db_handler = DatabaseHandler("task.db")
    
    # 创建测试任务
    task_id = "test_task_001"
    db_handler.create_task(task_id, "https://example.com/video", "Firefox", True, True)
    
    # 更新任务状态
    db_handler.update_task_status(task_id, "processing", "正在下载音频...")
    
    # 保存任务结果
    result_data = {
        "transcription": "这是测试的识别结果",
        "timestamp": [[100, 500], [550, 800]],
        "srt": "1\n00:00:00,100 --> 00:00:00,500\n这是测试的识别结果"
    }
    db_handler.save_task_result(task_id, result_data, "./download/audio_test.mp3")
    
    # 获取任务信息
    task_info = db_handler.get_task_by_id(task_id)
    print("任务信息:", task_info)
    
    # 获取最近任务列表
    recent_tasks = db_handler.get_recent_tasks(10)
    print(f"最近{len(recent_tasks)}个任务")