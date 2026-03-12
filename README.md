# ComicsPuncher 漫画平台自动签到助手

本项目是一个基于 Python 的自动化工具，旨在帮助用户实现 **哔咔漫画 (PicaComic)** 与 **禁漫天堂 (JMComic)** 的每日自动签到与打卡活跃。

## 🌟 功能特性

- **哔咔漫画**: 参考了[Golang版的哔咔漫画API](https://github.com/niuhuan/pica-go)，支持自动登录与每日打卡。
- **禁漫天堂**: 基于 `jmcomic` 库，模拟移动端 API 交互，登录即自动完成活跃。
- **多平台支持**: 适配 Windows/Linux 环境，支持配置 HTTP 代理。

## 🚀 快速开始

### 1. 环境准备

确保你的系统中已安装 Python 3.8+。

### 2. 安装依赖

```bash
pip install requests jmcomic
```

### 3. 账号配置
在运行之前，请打开 `main.py`，在 `用户配置区` 修改以下信息：
- `PICA_USER / PICA_PW`: 哔咔漫画账号密码。
- `JM_USER / JM_PW`: 禁漫天堂账号密码。
- `MY_PROXY`: **(重要)** 如果你在国内运行，请填写你的代理地址（如 `http://127.0.0.1:7897`），否则无法连接服务器。如果服务器在海外，请保持为空。

---

1. **(可选) 任务计划**:
如果你想每天自动跑，可以在 Windows “任务计划程序” 中创建一个基本任务，程序指向 `python.exe`，参数指向 `main.py` 的完整路径。

---

### 4. Linux 平台部署 (服务器挂机)

建议将脚本部署在海外 VPS（如腾讯云轻量香港、AWS、搬瓦工等），可省去代理配置。

#### **Crontab 定时任务**

1. **安装环境 (以 Ubuntu 为例)**:

```bash
sudo apt update
sudo apt install python3-pip
pip3 install -r requirements.txt
```

2. **设置定时任务**:

输入 `crontab -e`，在文件末尾添加以下行：
```bash
# 每天凌晨 08:30 自动执行打卡并记录日志
30 8 * * * /usr/bin/python3 /root/ComicsPuncher/main.py >> /root/ComicsPuncher/log.txt 2>&1
```

---

### 4. 常见问题 (FAQ)
* Q: 哔咔登录报错 `ERROR - 登录失败: {'code': 400, ...}`
  * A: 通常是签名密钥过期或代理失效。本项目已同步最新的签名算法。


* Q: 禁漫天堂域名无法连接？
  * A: 脚本会自动通过官方 API 更新最新域名，请确保你的网络能够访问 JM 的分流服务器。
