import json
import logging

from jmcomic import JmOption


class JmPuncher:
    """
    禁漫天堂自动签到类
    基于 jmcomic 库实现，模拟网页端登录并执行每日签到
    """

    def __init__(self, username, password, proxy=None):
        self.username = username
        self.password = password
        self.proxy = proxy

    def run(self):
        try:
            client = self._build_client()
            self._do_login(client)
            self._do_sign(client)
        except Exception as e:
            logging.error(f"JM 运行异常: {e}", exc_info=True)
            print(f"JM 签到失败: {e}")

    def _build_client(self):
        # 尝试使用 curl_cffi（支持 TLS 指纹伪装），失败则回退到 requests
        postman_type = self._detect_postman_type()
        logging.info(f"使用 {postman_type} 作为 HTTP 后端")

        meta_data = {}
        if postman_type == "curl_cffi":
            meta_data["impersonate"] = "chrome110"

        if self.proxy:
            meta_data["proxies"] = {"http": self.proxy, "https": self.proxy}

        option = JmOption.construct(
            {
                "client": {
                    "impl": "html",
                    "retry_times": 3,
                    "postman": {
                        "type": postman_type,
                        "meta_data": meta_data,
                    },
                }
            }
        )
        return option.build_jm_client()

    @staticmethod
    def _detect_postman_type():
        try:
            import curl_cffi  # noqa: F401
            return "curl_cffi"
        except ImportError:
            return "requests"

    def _do_login(self, client):
        logging.info(f"正在登录禁漫 (用户: {self.username})...")
        resp = client.login(self.username, self.password)

        if resp.status_code != 200:
            raise RuntimeError(f"登录失败，HTTP {resp.status_code}")

        cookies = dict(resp.cookies)
        # JMcomic 登录成功后会在 Cookie 中设置 remember_id / remember / yuo1
        if not any(k in cookies for k in ("remember_id", "remember", "yuo1", "AVS")):
            # 可能是密码错误或账号不存在
            logging.error(f"登录响应未包含有效会话 Cookie，请检查账号密码")
            raise RuntimeError("登录失败，请检查账号密码是否正确")

        logging.info(f"禁漫登录成功 (用户: {self.username})")

    def _do_sign(self, client):
        logging.info("正在执行禁漫签到...")
        resp = client.get_jm_html("/ajax/user_daily_sign")

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
