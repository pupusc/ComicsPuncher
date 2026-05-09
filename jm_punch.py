import json
import logging
import random
import time

from jmcomic import JmOption


# ---- 网络容错配置 ----
REQUEST_TIMEOUT = 25  # 单次请求超时（秒）
MAX_RETRIES = 2  # 应用层重试次数（仅对可重试错误生效）
RETRY_BACKOFF_BASE = 2  # 重试退避基数（秒）

# 预置域名，用于动态域名解析失败或 GitHub Actions IP 被封锁时的回退
FALLBACK_HTML_DOMAINS = [
    "18comic.vip",
    "18comic.org",
]
FALLBACK_API_DOMAINS = [
    "www.cdnhjk.net",
    "www.cdngwc.cc",
    "www.cdngwc.net",
]

# HTTP 403/401 为永久性拒绝，重试无意义
_NON_RETRYABLE_KW = ("403", "401", "Forbidden", "Unauthorized")


def _is_retryable(error_msg: str) -> bool:
    msg = str(error_msg)
    return not any(kw in msg for kw in _NON_RETRYABLE_KW)


def _retry_with_backoff(func, max_retries=MAX_RETRIES):
    """带指数退避的重试包装器，403/401 等拒绝类错误跳过重试直接抛出"""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            last_exc = e
            if attempt == max_retries or not _is_retryable(str(e)):
                raise
            delay = RETRY_BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1)
            logging.warning(
                f"请求失败 (第 {attempt + 1}/{max_retries + 1} 次): {e}，{delay:.1f}s 后重试"
            )
            time.sleep(delay)
    raise last_exc


# ---- 响应对象兼容层 ----
# jmcomic 的 HTML 客户端返回 requests.Response（有 .status_code / .cookies / .text），
# API 客户端返回 JmApiResp（状态码在 .resp.status_code，cookies 在 .resp.cookies）。

def _resp_status(resp) -> int:
    """兼容获取 HTTP 状态码"""
    if raw := getattr(resp, 'resp', None):
        return getattr(raw, 'status_code', -1)
    return getattr(resp, 'status_code', -1)


def _resp_cookies(resp) -> dict:
    """兼容获取响应 cookies 字典"""
    if raw := getattr(resp, 'resp', None):
        return dict(getattr(raw, 'cookies', {}))
    return dict(getattr(resp, 'cookies', {}))


def _resp_text(resp) -> str:
    """兼容获取响应文本"""
    if raw := getattr(resp, 'resp', None):
        return getattr(raw, 'text', '')
    return getattr(resp, 'text', '')


class JmPuncher:
    """
    禁漫天堂自动签到类

    三层回退策略（针对 GitHub Actions 环境优化）:
      策略1 — HTML 网页端: curl_cffi 指纹伪装，但 GitHub Actions IP 常被 Cloudflare 拦截 (403)
      策略2 — API 移动端: 使用移动端 API 域名（cdnhjk.net 等），Cloudflare 防护较宽松
      策略3 — 直接 HTTP: 绕过 jmcomic 框架，最朴素的 HTTP 请求兜底
    """

    def __init__(self, username, password, proxy=None):
        self.username = username
        self.password = password
        self.proxy = proxy

    # ============================
    # 主流程
    # ============================

    def run(self):
        strategies = [
            ("HTML网页端", self._try_via_html_client),
            ("API移动端", self._try_via_api_client),
            ("直接HTTP(兜底)", self._try_via_direct_http),
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

    # ============================
    # 策略1: HTML 网页端
    # ============================

    def _try_via_html_client(self):
        client = self._build_client("html", FALLBACK_HTML_DOMAINS)
        self._do_login(client)
        self._do_sign_via_html_client(client)

    # ============================
    # 策略2: API 移动端
    # ============================

    def _try_via_api_client(self):
        # API 域名通常 Cloudflare 防护较宽松，GitHub Actions 可连通
        client = self._build_client("api", FALLBACK_API_DOMAINS)
        self._do_login(client)

        # API 客户端没有 get_jm_html()，需要自行发 HTTP 请求签到。
        # 关键：必须使用 API 域名发签到请求，因为登录 cookies 绑定在 API 域上。
        domain = client.get_domain_list()[0]
        cookies = client.get_meta_data('cookies') or {}
        logging.info(f"使用 API 域名 [{domain}] 执行签到")
        self._do_sign_via_direct_http(domain=domain, cookies=cookies)

    # ============================
    # 策略3: 直接 HTTP（完全不依赖 jmcomic 框架）
    # ============================

    def _try_via_direct_http(self):
        logging.info("使用直接 HTTP 请求进行签到...")
        # 遍历候选域名，找到可用的后手动登录+签到
        domain = self._probe_domain(FALLBACK_HTML_DOMAINS + FALLBACK_API_DOMAINS)
        if not domain:
            raise RuntimeError("无法连接到任何禁漫域名")
        self._do_sign_via_direct_http(domain=domain, cookies=None)

    # ============================
    # 客户端构建
    # ============================

    def _build_client(self, impl, fallback_domains):
        postman_type = self._detect_postman_type()

        meta_data = {"timeout": REQUEST_TIMEOUT}
        if postman_type == "curl_cffi":
            meta_data["impersonate"] = "chrome124"
        if self.proxy:
            meta_data["proxies"] = {"http": self.proxy, "https": self.proxy}

        make_config = lambda domains: {
            "client": {
                "impl": impl,
                "domain": domains,
                "retry_times": 1,  # 减少 jmcomic 内部重试，由本模块控制
                "postman": {
                    "type": postman_type,
                    "meta_data": meta_data,
                },
            }
        }

        # 先尝试动态域名解析（访问 jm365.work 永久重定向页）
        try:
            option = JmOption.construct(make_config([]))
            return option.build_jm_client()
        except Exception as e:
            logging.warning(f"动态域名解析失败，使用预置域名: {fallback_domains}")
            option = JmOption.construct(make_config(fallback_domains))
            return option.build_jm_client()

    @staticmethod
    def _detect_postman_type():
        try:
            import curl_cffi  # noqa: F401
            return "curl_cffi"
        except ImportError:
            return "requests"

    # ============================
    # 登录（HTML & API 客户端通用）
    # ============================

    def _do_login(self, client):
        logging.info(f"正在登录禁漫 (用户: {self.username})...")

        def action():
            resp = client.login(self.username, self.password)
            status = _resp_status(resp)
            if status not in (200, -1):
                raise RuntimeError(f"登录失败，HTTP {status}")
            cookies = _resp_cookies(resp)
            if not any(k in cookies for k in ("remember_id", "remember", "yuo1", "AVS")):
                raise RuntimeError("登录响应未包含有效会话 Cookie，请检查账号密码")
            return resp

        _retry_with_backoff(action)
        logging.info(f"禁漫登录成功 (用户: {self.username})")

    # ============================
    # 签到 — HTML 客户端路径
    # ============================

    def _do_sign_via_html_client(self, client):
        logging.info("正在执行禁漫签到...")
        resp = _retry_with_backoff(
            lambda: client.get_jm_html("/ajax/user_daily_sign", timeout=REQUEST_TIMEOUT)
        )
        self._parse_and_handle(_resp_text(resp))

    # ============================
    # 签到 — 直接 HTTP 路径（策略2/3共用）
    # ============================

    def _do_sign_via_direct_http(self, domain, cookies):
        import requests as req

        session = req.Session()
        if self.proxy:
            session.proxies = {"http": self.proxy, "https": self.proxy}

        # 如果已有 cookies（策略2），直接注入 session
        if cookies:
            for k, v in cookies.items():
                session.cookies.set(k, v, domain=domain)
        else:
            # 没有 cookies → 先登录（策略3）
            self._direct_login(session, domain)

        sign_resp = _retry_with_backoff(
            lambda: session.get(
                f"https://{domain}/ajax/user_daily_sign",
                timeout=REQUEST_TIMEOUT,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 "
                        "Mobile Safari/537.36"
                    ),
                    "Accept": "application/json, text/plain, */*",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
        )
        self._parse_and_handle(sign_resp.text)

    def _direct_login(self, session, domain):
        """策略3专用：直接 HTTP 登录"""
        logging.info("直接HTTP登录中...")
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
            raise RuntimeError(f"登录失败，HTTP {resp.status_code}")
        if not any(k in dict(resp.cookies) for k in ("remember_id", "remember", "yuo1", "AVS")):
            raise RuntimeError("登录失败，未获取到有效会话 Cookie")
        logging.info("直接HTTP登录成功")

    # ============================
    # 域名探测
    # ============================

    def _probe_domain(self, candidates, timeout=8):
        """按顺序探测可连通的域名，返回第一个 HTTP 200 的域名"""
        seen = set()
        for domain in candidates:
            if domain in seen:
                continue
            seen.add(domain)
            try:
                import requests as req
                resp = req.get(
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

    # ============================
    # 签到结果解析
    # ============================

    def _parse_and_handle(self, text: str):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logging.warning(f"签到响应非 JSON: {text[:200]}")
            print("签到状态未知，请检查日志")
            return
        self._handle_sign_result(data)

    def _handle_sign_result(self, data):
        if not isinstance(data, dict):
            print(f"签到状态未知: {data}")
            return

        if data.get("error") == "finished":
            logging.info("今日已签到，无需重复签到")
            print("签到结果: 今日已签到")
        elif data.get("errorMsg") == "Not legal.ajax":
            logging.error("签到失败: AJAX 验证未通过，可能登录态已失效")
            print("签到失败: 登录验证未通过")
        elif "msg" in data:
            msg = data["msg"]
            logging.info(f"禁漫签到成功: {msg}")
            print(f"签到结果: {msg}")
        else:
            logging.info(f"签到响应: {data}")
            print(f"签到状态: {data}")
