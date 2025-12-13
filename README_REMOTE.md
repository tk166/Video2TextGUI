注：这是远程的Server的README文件，并不是需要在这里实现的功能

# Audio2Text 远程接口版本

这个版本提供了通过HTTP API远程触发视频转文字功能的能力。

## 功能特性

- 通过RESTful API接收处理请求
- 异步处理视频，避免阻塞
- 实时查询处理状态和结果
- 完整的日志记录和错误处理
- 支持加密Cookie数据传输（更安全的方式）

## 安装依赖

```bash
pip install -r requirements.txt
```

## 启动服务

```bash
python converter_app_remote.py
```

服务将启动在 `http://localhost:5001`

## API 接口文档

### 1. 健康检查

**URL**: `GET /api/health`

**响应示例**:
```json
{
  "status": "healthy",
  "device": "cuda",
  "model_loaded": true
}
```

### 2. 开始处理视频

**URL**: `POST /api/process`

**请求体**:
```json
{
  "url": "https://www.youtube.com/watch?v=example",
  "cookie_file": "/path/to/cookies.txt",  // 可选，cookie文件路径
  "encrypted_cookie_data": "ENCRYPTED_COOKIE_DATA_HERE",  // 可选，加密的cookie数据（优先级高于cookie_file）
  "keep_audio": true  // 可选，是否保留音频文件，默认false
}
```

**响应示例**:
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "任务已启动，请使用任务ID查询处理状态"
}
```

### 3. 查询任务状态

**URL**: `GET /api/status/<task_id>`

**响应示例 (处理中)**:
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "progress": "正在下载音频 (yt-dlp)..."
}
```

**响应示例 (已完成)**:
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "progress": "🎉 处理全部完成！",
  "result": {
    "transcription": "这是识别出的文字内容...",
    "srt": "1\n00:00:00,000 --> 00:00:05,000\n这是识别出的文字内容...",
    "timestamp": [[100, 500], [550, 800], [850, 1200]]
  }
}
```

### 5. 下载音频文件

**URL**: `GET /api/audio/<task_id>`

**说明**: 下载指定任务的原始音频文件。仅在处理请求中设置了`keep_audio=true`时可用。

**响应**: 音频文件二进制数据

### 6. 删除音频文件

**URL**: `DELETE /api/audio/<task_id>`

**说明**: 删除指定任务的音频文件以释放存储空间。

**响应示例**:
```json
{
  "message": "音频文件删除成功"
}
```

### 7. 清理过期文件

**URL**: `POST /api/cleanup`

**说明**: 清理系统中过期的音频文件。

**请求体**:
```json
{
  "max_age_hours": 24  // 可选，过期时间（小时），默认24小时
}
```

**响应示例**:
```json
{
  "message": "清理完成，删除了 5 个过期文件",
  "deleted_count": 5
}
```

## 返回数据说明

### transcription
识别出的完整文本内容。

### srt
自动生成的SRT格式字幕内容，包含时间戳和对应的文本。

### timestamp
原始时间戳数据，是一个二维数组，每个元素包含两个数值：
- 第一个数值：字符开始时间（毫秒）
- 第二个数值：字符结束时间（毫秒）

格式：`[[start_time_ms, end_time_ms], [start_time_ms, end_time_ms], ...]`

例如：`[[100, 500], [550, 800], [850, 1200]]` 表示第一个字符从100ms开始到500ms结束。

### audio_url
如果请求中设置了`keep_audio=true`且处理成功，此字段将包含音频文件的下载URL。
可以通过该URL下载原始音频文件。

格式：`/api/audio/{task_id}`

### raw
原始的识别结果数据，包含更多详细信息。

## 使用时间戳数据自定义字幕

时间戳数据允许客户端自行实现字幕生成功能，例如：

1. **自定义分行逻辑**：根据语义或固定字符数分行
2. **调整时间范围**：微调字幕显示时间
3. **特殊效果**：实现卡拉OK效果等

### Python示例代码

```python
import requests

# 获取处理结果
response = requests.get('http://localhost:5001/api/status/YOUR_TASK_ID')
result = response.json()['result']

# 提取文本和时间戳
text = result['transcription']
timestamps = result['timestamp']

# 使用时间戳生成自定义字幕
def generate_custom_subtitles(text, timestamps, chars_per_line=20):
    subtitles = []
    for i in range(0, len(text), chars_per_line):
        line_text = text[i:i+chars_per_line]
        start_idx = i
        end_idx = min(i + chars_per_line - 1, len(text) - 1)

        if start_idx < len(timestamps) and end_idx < len(timestamps):
            start_time = timestamps[start_idx][0]
            end_time = timestamps[end_idx][1]
            subtitles.append({
                'text': line_text,
                'start_time': start_time,
                'end_time': end_time
            })

    return subtitles

custom_subs = generate_custom_subtitles(text, timestamps)
for i, sub in enumerate(custom_subs):
    print(f"{i+1}\\n{format_time(sub['start_time'])} --> {format_time(sub['end_time'])}\\n{sub['text']}\\n")
```

# 使用示例

### Python 示例

```python
import requests
import time

# 启动处理任务（不保留音频）
response = requests.post('http://localhost:5001/api/process',
                        json={'url': 'https://www.youtube.com/watch?v=example'})
task_id = response.json()['task_id']

# 启动处理任务（保留音频文件）
response = requests.post('http://localhost:5001/api/process',
                        json={
                            'url': 'https://www.youtube.com/watch?v=example',
                            'keep_audio': True
                        })
task_id = response.json()['task_id']

# 启动处理任务（使用普通的cookie文件）
response = requests.post('http://localhost:5001/api/process',
                        json={
                            'url': 'https://www.youtube.com/watch?v=example',
                            'cookie_file': '/path/to/cookies.txt'
                        })
task_id = response.json()['task_id']

# 启动处理任务（使用加密的cookie数据）
from crypto_utils import encrypt_data

# 读取原始cookie文件内容
with open('/path/to/cookies.txt', 'r') as f:
    cookie_content = f.read()

# 加密cookie数据
encrypted_cookie_data = encrypt_data(cookie_content)

# 发送请求
response = requests.post('http://localhost:5001/api/process',
                        json={
                            'url': 'https://www.youtube.com/watch?v=example',
                            'encrypted_cookie_data': encrypted_cookie_data,
                            'keep_audio': True
                        })
task_id = response.json()['task_id']

# 轮询任务状态
while True:
    response = requests.get(f'http://localhost:5001/api/status/{task_id}')
    result = response.json()

    if result['status'] == 'completed':
        print("转录结果:", result['result']['transcription'])

        # 如果保留了音频，可以下载
        if 'audio_url' in result['result']:
            audio_response = requests.get(f"http://localhost:5001{result['result']['audio_url']}")
            with open('downloaded_audio.mp3', 'wb') as f:
                f.write(audio_response.content)
            print("音频文件已下载")

            # 使用完后删除音频文件以节省空间
            delete_response = requests.delete(f"http://localhost:5001/api/audio/{task_id}")
            if delete_response.status_code == 200:
                print("音频文件已删除")
        break
    elif result['status'] == 'failed':
        print("处理失败:", result['error'])
        break

    print("当前进度:", result['progress'])
    time.sleep(5)

# 清理过期文件
cleanup_response = requests.post('http://localhost:5001/api/cleanup',
                               json={'max_age_hours': 24})
if cleanup_response.status_code == 200:
    print("过期文件清理完成")
```

### curl 示例

```bash
# 启动处理任务（不保留音频）
curl -X POST http://localhost:5001/api/process \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=example"}'

# 启动处理任务（保留音频文件）
curl -X POST http://localhost:5001/api/process \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=example", "keep_audio": true}'

# 启动处理任务（使用普通的cookie文件）
curl -X POST http://localhost:5001/api/process \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=example", "cookie_file": "/path/to/cookies.txt"}'

# 启动处理任务（使用加密的cookie数据）
# 注意：需要先使用crypto_utils.py加密cookie数据
curl -X POST http://localhost:5001/api/process \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=example", "encrypted_cookie_data": "ENCRYPTED_COOKIE_DATA_HERE", "keep_audio": true}'

# 查询任务状态
curl http://localhost:5001/api/status/YOUR_TASK_ID

# 下载音频文件（如果保留了音频）
curl http://localhost:5001/api/audio/YOUR_TASK_ID -o audio.mp3

# 删除音频文件
curl -X DELETE http://localhost:5001/api/audio/YOUR_TASK_ID

# 清理过期文件（默认24小时）
curl -X POST http://localhost:5001/api/cleanup

# 清理过期文件（指定时间）
curl -X POST http://localhost:5001/api/cleanup \
  -H "Content-Type: application/json" \
  -d '{"max_age_hours": 48}'

# 列出所有任务
curl http://localhost:5001/api/tasks
```

## 加密Cookie功能说明

为了提高安全性，本系统支持通过加密数据流传输cookie信息，而不是直接传递文件路径。

### 工作原理
1. 客户端使用共享密钥加密cookie数据
2. 将加密数据作为`encrypted_cookie_data`参数发送到API
3. 服务端使用相同的密钥解密数据
4. 将解密后的数据保存为临时文件供yt-dlp使用
5. 处理完成后自动清理临时文件

### 密钥管理
- 密钥存储在项目根目录的`key.txt`文件中
- 如果该文件不存在，系统会自动生成一个随机密钥
- 生产环境建议使用安全的方式管理和分发密钥

### 加密工具

```python
import base64
from cryptography.fernet import Fernet

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

    # 先进行base64解码
    encrypted_data = base64.urlsafe_b64decode(encrypted_data.encode())

    # 解密数据
    decrypted_data = f.decrypt(encrypted_data)

    return decrypted_data.decode()

# 读取原始cookie文件内容
with open('/path/to/cookies.txt', 'r') as f:
    cookie_content = f.read()

# 加密cookie数据
encrypted_cookie_data = encrypt_data(cookie_content)
```

## 日志

日志将输出到控制台和 `converter_app_remote.log` 文件中。
