"""
Cookie处理模块
提供获取浏览器Cookie、加密和异常处理功能
"""

import browser_cookie3
import base64
from cryptography.fernet import Fernet
import traceback


class CookieHandler:
    """处理浏览器Cookie获取和加密的类"""
    
    def __init__(self, key_file="key.txt"):
        """
        初始化Cookie处理器
        
        Args:
            key_file (str): 加密密钥文件路径
        """
        self.key_file = key_file
        self.encryption_key = self._load_encryption_key()
    
    def _load_encryption_key(self):
        """
        从文件加载加密密钥
        
        Returns:
            bytes: 加密密钥，如果加载失败返回None
        """
        try:
            with open(self.key_file, "r") as f:
                key = f.read().strip()
                # 验证密钥长度（32字节base64编码后的长度应该是43）
                if len(key) != 43:
                    raise ValueError("Invalid key length")
                return key.encode()
        except FileNotFoundError:
            print(f"错误: 找不到密钥文件 {self.key_file}")
            return None
        except Exception as e:
            print(f"读取密钥文件时出错: {e}")
            return None
    
    def get_cookies(self, browser_name):
        """
        根据浏览器名称获取Cookie
        
        Args:
            browser_name (str): 浏览器名称 ("firefox", "edge", "chrome")
            
        Returns:
            str: Cookie字符串，格式为"name1=value1; name2=value2"，获取失败返回None
        """
        try:
            # 根据浏览器类型获取Cookie
            if browser_name.lower() == "firefox":
                cookies = browser_cookie3.firefox()
            elif browser_name.lower() == "edge":
                cookies = browser_cookie3.edge()
            elif browser_name.lower() == "chrome":
                cookies = browser_cookie3.chrome()
            else:
                raise ValueError(f"不支持的浏览器类型: {browser_name}")
            
            # 将Cookie对象转换为字符串格式
            cookie_str = ""
            for cookie in cookies:
                # 只添加有名称和值的Cookie
                if cookie.name and cookie.value:
                    cookie_str += f"{cookie.name}={cookie.value}; "
            
            # 移除末尾的分号和空格
            return cookie_str.rstrip("; ") if cookie_str else ""
            
        except browser_cookie3.BrowserNotInstalledError:
            print(f"错误: {browser_name}浏览器未安装")
            return None
        except PermissionError:
            print(f"错误: 没有权限访问{browser_name}浏览器数据")
            return None
        except Exception as e:
            print(f"获取{browser_name}浏览器Cookie时发生未知错误: {e}")
            traceback.print_exc()
            return None
    
    def encrypt_cookies(self, cookie_data):
        """
        加密Cookie数据
        
        Args:
            cookie_data (str): 要加密的Cookie数据
            
        Returns:
            str: 加密后的Cookie数据(base64编码)，加密失败返回None
        """
        try:
            # 检查是否有加密密钥
            if self.encryption_key is None:
                print("错误: 没有可用的加密密钥")
                return None
            
            # 使用Fernet加密
            f = Fernet(self.encryption_key)
            if isinstance(cookie_data, str):
                cookie_data = cookie_data.encode()
            
            encrypted_data = f.encrypt(cookie_data)
            return base64.urlsafe_b64encode(encrypted_data).decode()
            
        except Exception as e:
            print(f"加密Cookie数据时出错: {e}")
            return None
    
    def get_and_encrypt_cookies(self, browser_name):
        """
        获取并加密指定浏览器的Cookie
        
        Args:
            browser_name (str): 浏览器名称
            
        Returns:
            dict: 包含结果的字典
                - success (bool): 是否成功
                - data (str): 加密后的Cookie数据（成功时）
                - message (str): 结果消息
        """
        # 获取Cookie
        cookie_data = self.get_cookies(browser_name)
        if cookie_data is None:
            return {
                "success": False,
                "data": None,
                "message": f"无法获取{browser_name}浏览器的Cookie"
            }
        
        if not cookie_data:
            return {
                "success": True,
                "data": "",
                "message": f"在{browser_name}浏览器中未找到Cookie"
            }
        
        # 加密Cookie
        encrypted_data = self.encrypt_cookies(cookie_data)
        if encrypted_data is None:
            return {
                "success": False,
                "data": None,
                "message": "Cookie加密失败"
            }
        
        return {
            "success": True,
            "data": encrypted_data,
            "message": "Cookie获取并加密成功"
        }


# 使用示例
if __name__ == "__main__":
    # 创建Cookie处理器实例
    handler = CookieHandler("key.txt")
    
    # 测试获取不同浏览器的Cookie
    browsers = ["firefox", "edge", "chrome"]
    
    for browser in browsers:
        print(f"\n--- 测试 {browser} 浏览器 ---")
        result = handler.get_and_encrypt_cookies(browser)
        
        if result["success"]:
            print(f"状态: {result['message']}")
            if result["data"]:
                print(f"加密数据长度: {len(result['data'])} 字符")
            else:
                print("未找到Cookie数据")
        else:
            print(f"失败: {result['message']}")