import json
import logging
import time
import random

from jmcomic import JmOption


# ---- 网络容错配置 ----
REQUEST_TIMEOUT = 25  # 单次请求超时（秒）
MAX_RETRIES = 3  # 应用层重试次数
RETRY_BACKOFF_BASE = 2  # 重试退避基数（秒），实际延迟 = base * (2 ** n) ± jitter

# 预置禁漫域名，用于动态域名解析失败时的回退
# 当 jm365.work 重定向服务不可达时，直接用这些域名
FALLBACK_HTML_DOMAINS = [
    "18comic.vip",
    "18comic.org",
]
FALLBACK_API_DOMAINS = [
    "www.cdnhjk.net",
    "www.cdngwc.cc",
    "www.cdngwc.net",
]


def _retry_with_backoff(func, max_retries=MAX_RETRIES):
    """带指数退避的重试包装器"""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            last_exc = e
            if attempt == max_retries:
                raise
            delay = RETRY_BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1)
            logging.warning(
                f"请求失败 (第 {attempt + 1}/{max_retries + 1} 次): {e}，{delay:.1f}s 后重试"
            )
            time.sleep(delay)
    raise last_exc  # unreachable


class JmPuncher:
    """
    禁漫天堂自动签到类
    基于 jmcomic 库实现，具备多策略回退和网络容错能力：
      - 策略1: HTML 网页端（curl_cffi 指纹伪装）
      - 策略2: API 移动端（独立域名，可能绕过部分封锁）
      - 策略3: 直接 HTTP 请求（绕过 jmcomic 域名解析，兜底方案）
    """

    def __init__(self, username, password, proxy=None):
        self.username = username
        self.password = password
        self.proxy = proxy

    def run(self):
        strategies = [
            ("HTML网页端", self._try_html_client),
            ("API移动端", self._try_api_client),
            ("直接HTTP(兜底)", self._try_direct_http),
        ]

        for name, strategy in strategies:
            try:
                logging.info(f"尝试策略: {name}")
                strategy()
                return
            except Exception as e:
                logging.warning(f"策略 [{name}] 失败: {e}")

        logging.error("所有签到策略均失败")
        print("JM 签到失败: 所有策略均无法完成签到")

    # ===== 策略1: HTML 网页端 =====
    def _try_html_client(self):
        client = self._build_client(impl="html", fallback_domains=FALLBACK_HTML_DOMAINS)
        self._do_login(client, impl_label="HTML")
        self._do_sign(client)

    # ===== 策略2: API 移动端 =====
    def _try_api_client(self):
        client = self._build_client(impl="api", fallback_domains=FALLBACK_API_DOMAINS)
        self._do_login(client, impl_label="API")
        self._do_sign(client)

    # ===== 策略3: 直接 HTTP 请求（绕过 jmcomic 域名检测） =====
    def _try_direct_http(self):
        logging.info("使用直接 HTTP 请求进行签到...")
        import requests as req

        session = req.Session()
        if self.proxy:
            session.proxies = {"http": self.proxy, "https": self.proxy}

        # 遍历候选域名尝试登录
        domain = self._resolve_working_domain(session)
        if not domain:
            raise RuntimeError("无法连接到任何禁漫域名")

        # 登录
        resp = session.post(
            f"https://{domain}/login",
            data={
                "username": self.username,
                "password": self.password,
                "id_remember": "on",
                "login_remember": "on",
                "submit_login": "",
            },
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"直接HTTP登录失败，HTTP {resp.status_code}")

        cookies = dict(resp.cookies)
        if not any(k in cookies for k in ("remember_id", "remember", "yuo1", "AVS")):
            raise RuntimeError("直接HTTP登录失败，未获取到有效会话 Cookie")

        logging.info("直接HTTP登录成功")

        # 签到
        sign_resp = session.get(
            f"https://{domain}/ajax/user_daily_sign",
            timeout=REQUEST_TIMEOUT,
        )

        try:
            data = sign_resp.json()
        except json.JSONDecodeError:
            logging.warning(f"签到响应非 JSON: {sign_resp.text[:200]}")
            print("签到状态未知，请检查日志")
            return

        self._handle_sign_result(data)

    def _resolve_working_domain(self, session, timeout=10):
        """按优先级检测可连通的域名"""
        candidates = FALLBACK_HTML_DOMAINS + FALLBACK_API_DOMAINS
        # 去重并保持顺序
        seen = set()
        candidates = [d for d in candidates if not (d in seen or seen.add(d))]

        for domain in candidates:
            try:
                resp = session.get(
                    f"https://{domain}/",
                    timeout=timeout,
                    allow_redirects=True,
                )
                if resp.status_code == 200:
                    logging.info(f"找到可用域名: {domain}")
                    return domain
            except Exception as e:
                logging.debug(f"域名 {domain} 不可用: {e}")

        return None

    # ===== 公共方法 =====
    def _build_client(self, impl, fallback_domains):
        """构建 jmcomic 客户端，优先动态域名解析，失败则用预置域名"""

        postman_type = self._detect_postman_type()
        logging.info(f"使用 {postman_type} 作为 HTTP 后端")

        meta_data = {"timeout": REQUEST_TIMEOUT}
        if postman_type == "curl_cffi":
            meta_data["impersonate"] = "chrome110"

        if self.proxy:
            meta_data["proxies"] = {"http": self.proxy, "https": self.proxy}

        base_config = {
            "client": {
                "impl": impl,
                "retry_times": MAX_RETRIES,
                "postman": {
                    "type": postman_type,
                    "meta_data": meta_data,
                },
            }
        }

        # 先尝试动态域名解析（build_jm_client 内部触发）
        option = JmOption.construct(base_config)
        try:
            return option.build_jm_client()
        except Exception as e:
            logging.warning(f"动态域名解析失败 ({e})，回退到预置域名: {fallback_domains}")
            # 用预置域名重新构建
            fallback_config = {
                "client": {
                    "impl": impl,
                    "domain": fallback_domains,
                    "retry_times": MAX_RETRIES,
                    "postman": {
                        "type": postman_type,
                        "meta_data": meta_data,
                    },
                }
            }
            option = JmOption.construct(fallback_config)
            return option.build_jm_client()

    def _do_login(self, client, impl_label=""):
        label = f"[{impl_label}] " if impl_label else ""
        logging.info(f"{label}正在登录禁漫 (用户: {self.username})...")

        def login_action():
            resp = client.login(self.username, self.password)
            if resp.status_code != 200:
                raise RuntimeError(f"登录失败，HTTP {resp.status_code}")
            cookies = dict(resp.cookies)
            if not any(k in cookies for k in ("remember_id", "remember", "yuo1", "AVS")):
                raise RuntimeError("登录响应未包含有效会话 Cookie，请检查账号密码")
            return resp

        _retry_with_backoff(login_action)
        logging.info(f"{label}禁漫登录成功 (用户: {self.username})")

    def _do_sign(self, client):
        logging.info("正在执行禁漫签到...")

        def sign_action():
            resp = client.get_jm_html("/ajax/user_daily_sign", timeout=REQUEST_TIMEOUT)
            return resp

        resp = _retry_with_backoff(sign_action)

        try:
            data = json.loads(resp.text)
        except json.JSONDecodeError:
            logging.warning(f"签到响应非 JSON: {resp.text[:200]}")
            print("签到状态未知，请检查日志")
            return

        self._handle_sign_result(data)

    def _handle_sign_result(self, data):
        if not isinstance(data, dict):
            print(f"签到状态未知: {data}")
            return

        # 已经签到过
        if data.get("error") == "finished":
            logging.info("今日已签到，无需重复签到")
            print("签到结果: 今日已签到")

        # AJAX 验证失败 (未登录)
        elif data.get("errorMsg") == "Not legal.ajax":
            logging.error("签到失败: AJAX 验证未通过，可能登录态已失效")
            print("签到失败: 登录验证未通过")

        # 签到成功
        elif "msg" in data:
            msg = data["msg"]
            logging.info(f"禁漫签到成功: {msg}")
            print(f"签到结果: {msg}")

        # 兜底
        else:
            logging.info(f"签到响应: {data}")
            print(f"签到状态: {data}")

    @staticmethod
    def _detect_postman_type():
        try:
            import curl_cffi  # noqa: F401
            return "curl_cffi"
        except ImportError:
            return "requests"
