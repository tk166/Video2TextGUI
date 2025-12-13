#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
加密/解密工具模块
提供cookie数据的加密和解密功能
"""

import os
import base64
import tempfile
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# 默认密钥文件路径
DEFAULT_KEY_FILE = os.path.join(os.path.dirname(__file__), "key.txt")

def generate_key(password=None, salt=b"salt_"):
    """
    生成加密密钥
    
    Args:
        password (str, optional): 密码，如果不提供则从key.txt文件读取
        salt (bytes): 盐值
        
    Returns:
        bytes: 加密密钥
    """
    if password is None:
        # 从文件读取密码
        if os.path.exists(DEFAULT_KEY_FILE):
            with open(DEFAULT_KEY_FILE, 'r') as f:
                password = f.read().strip()
        else:
            # 如果文件不存在，生成一个随机密码并保存
            import secrets
            password = secrets.token_urlsafe(32)
            with open(DEFAULT_KEY_FILE, 'w') as f:
                f.write(password)
    
    if isinstance(password, str):
        password = password.encode()
    
    # 使用PBKDF2生成密钥
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password))
    return key

def encrypt_data(data, password=None):
    """
    加密数据
    
    Args:
        data (str or bytes): 要加密的数据
        password (str, optional): 密码
        
    Returns:
        str: 加密后的数据(base64编码)
    """
    key = generate_key(password)
    f = Fernet(key)
    
    if isinstance(data, str):
        data = data.encode()
    
    encrypted_data = f.encrypt(data)
    return base64.urlsafe_b64encode(encrypted_data).decode()

def decrypt_data(encrypted_data, password=None):
    """
    解密数据
    
    Args:
        encrypted_data (str): 加密的数据(base64编码)
        password (str, optional): 密码
        
    Returns:
        str: 解密后的数据
    """
    key = generate_key(password)
    f = Fernet(key)
    
    encrypted_data = base64.urlsafe_b64decode(encrypted_data.encode())
    decrypted_data = f.decrypt(encrypted_data)
    return decrypted_data.decode()

def save_encrypted_cookie(encrypted_cookie_data, password=None):
    """
    将加密的cookie数据保存为临时文件并返回文件路径
    
    Args:
        encrypted_cookie_data (str): 加密的cookie数据
        password (str, optional): 解密密码
        
    Returns:
        str: 临时cookie文件路径
    """
    try:
        # 解密数据
        cookie_content = decrypt_data(encrypted_cookie_data, password)
        
        # 创建临时文件
        temp_cookie_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
        temp_cookie_file.write(cookie_content)
        temp_cookie_file.close()
        
        return temp_cookie_file.name
    except Exception as e:
        raise Exception(f"保存加密cookie失败: {str(e)}")

# 示例用法
if __name__ == "__main__":
    # 生成密钥文件
    key = generate_key()
    print(f"密钥已生成并保存到 {DEFAULT_KEY_FILE}")
    
    # 示例数据
    sample_cookie = """# Netscape HTTP Cookie File
.youtube.com	TRUE	/	TRUE	1768000000	SID	XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
.youtube.com	TRUE	/	TRUE	1768000000	SSID	XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
"""
    
    # 加密数据
    encrypted = encrypt_data(sample_cookie)
    print(f"加密数据: {encrypted}")
    
    # 解密数据
    decrypted = decrypt_data(encrypted)
    print(f"解密数据: {decrypted}")
    
    # 保存为临时文件
    temp_file = save_encrypted_cookie(encrypted)
    print(f"临时文件: {temp_file}")
    
    # 清理临时文件
    if os.path.exists(temp_file):
        os.remove(temp_file)
        print("临时文件已清理")