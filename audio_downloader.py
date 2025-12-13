"""
音频文件下载模块
负责从远程服务下载音频文件并保存到本地
"""

import requests
import os
import sqlite3
from typing import Optional
from db_handler import DatabaseHandler
from pathvalidate import sanitize_filename


def download_audio_file(task_id: str, audio_url: str, db_handler: DatabaseHandler, date_str:str="251212", uploader:str="未知作者", title:str="未知标题") -> Optional[str]:
    """
    从远程服务下载音频文件并保存到本地
    
    Args:
        task_id (str): 任务ID
        audio_url (str): 音频文件的URL
        db_handler (DatabaseHandler): 数据库处理器实例
        
    Returns:
        str: 本地音频文件路径，如果下载失败则返回None
    """
    try:
        # 确保下载目录存在
        download_dir = "download"
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)
            
        # 构建完整的音频下载URL
        if audio_url.startswith("/"):
            full_url = f"http://tkmini.local:5001{audio_url}"
        else:
            full_url = audio_url
            
        # 使用任务ID作为文件名的一部分，确保唯一性
        filename = f"{date_str}_{uploader}_{title}_{task_id[:5]}.mp3"
        filename = sanitize_filename(filename)
        local_filepath = os.path.join(download_dir, filename)
        
        # 发送HTTP GET请求下载音频文件
        response = requests.get(full_url, timeout=60)
        
        # 检查响应状态
        if response.status_code == 200:
            # 保存音频文件到本地
            with open(local_filepath, "wb") as f:
                f.write(response.content)
                
            # 更新数据库中的音频文件路径
            if update_audio_file_path_in_db(task_id, local_filepath, db_handler):
                print(f"音频文件下载成功并保存到: {local_filepath}")
                return local_filepath
            else:
                print("音频文件下载成功，但更新数据库失败")
                return local_filepath
        else:
            print(f"下载音频文件失败: HTTP {response.status_code}")
            return None
            
    except requests.exceptions.Timeout:
        print("下载音频文件超时")
        return None
    except requests.exceptions.ConnectionError:
        print("下载音频文件时连接错误")
        return None
    except Exception as e:
        print(f"下载音频文件时发生未知错误: {str(e)}")
        return None


def update_audio_file_path_in_db(task_id: str, filepath: str, db_handler: DatabaseHandler) -> bool:
    """
    更新数据库中的音频文件路径
    
    Args:
        task_id (str): 任务ID
        filepath (str): 音频文件路径
        db_handler (DatabaseHandler): 数据库处理器实例
        
    Returns:
        bool: 是否成功更新
    """
    try:
        # 使用数据库处理器更新音频文件路径
        conn = sqlite3.connect(db_handler.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE tasks
            SET audio_file_path = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (filepath, task_id))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"更新数据库中的音频文件路径时出错: {str(e)}")
        return False


def cleanup_remote_audio(task_id: str) -> bool:
    """
    清理远程服务器上的音频文件
    
    Args:
        task_id (str): 任务ID
        
    Returns:
        bool: 是否成功清理
    """
    try:
        # 构建删除音频文件的API URL
        api_url = f"http://tkmini.local:5001/api/audio/{task_id}"
        
        # 发送DELETE请求
        response = requests.delete(api_url, timeout=30)
        
        # 检查响应状态
        if response.status_code == 200:
            print("远程音频文件清理成功")
            return True
        else:
            print(f"清理远程音频文件失败: HTTP {response.status_code}")
            return False
    except requests.exceptions.Timeout:
        print("清理远程音频文件请求超时")
        return False
    except requests.exceptions.ConnectionError:
        print("清理远程音频文件时连接错误")
        return False
    except Exception as e:
        print(f"清理远程音频文件时发生未知错误: {str(e)}")
        return False


# 使用示例
if __name__ == "__main__":
    # 测试代码
    db_handler = DatabaseHandler()
    # download_audio_file("test_task_id", "/api/audio/test_task_id", db_handler)
    pass