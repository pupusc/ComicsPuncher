import json
import logging
from jmcomic import JmOption


class JmPuncher:
    """
    禁漫天堂自动签到类
    基于 jmcomic 库实现，模拟移动端 API 登录
    """

    def __init__(self, username, password, proxy=None):
        self.username = username
        self.password = password
        self.proxy = proxy

    def run(self):
        try:
            # 构造禁漫配置 - 使用 HTML 客户端而不是 API 客户端
            option = JmOption.construct(
                {
                    "client": {
                        "impl": "html",
                        "username": self.username,
                        "password": self.password,
                        "proxies": {"http": self.proxy, "https": self.proxy}
                        if self.proxy
                        else None,
                        "postman_conf": {
                            "impersonate": "chrome110",
                            "verify": False
                        }
                    }
                }
            )
            client = option.build_jm_client()

            logging.info(f"正在尝试登录 JM (用户: {self.username})...")
            # 登录接口返回的数据包含完整用户信息
            resp = client.login(self.username, self.password)
            login_data = json.loads(resp.content)
            logging.info("=" * 20)
            logging.info(f"用户信息: {login_data}")
            logging.info("🎉 JM 登录活跃成功！")

            logging.info("=" * 20)

            # 使用 HTML 客户端的 get_jm_html 方法访问签到页面
            try:
                logging.info("正在访问签到页面...")
                sign_response = client.get_jm_html('/ajax/user_daily_sign')

                logging.info(f"签到响应状态码: {sign_response.status_code}")
                html_content = sign_response.text
                logging.info(f"签到响应内容: {html_content[:300]}")

                # 尝试解析 JSON 响应
                try:
                    SIGN_response_data = json.loads(html_content)

                    if SIGN_response_data:
                        if SIGN_response_data.get('errorMsg') == 'Not legal.ajax':
                            logging.error("AJAX 验证失败")
                            print("签到失败: AJAX 验证未通过")
                        elif "error" in SIGN_response_data and SIGN_response_data["error"] == "finished":
                            print("签到失败,你已经签到过了")
                        elif "msg" in SIGN_response_data:
                            print("签到成功:", SIGN_response_data['msg'])
                        else:
                            print("签到状态:", SIGN_response_data)
                    else:
                        print("签到失败或已签到")
                except json.JSONDecodeError:
                    # 如果返回的是 HTML 而不是 JSON
                    if "已经" in html_content or "已完成" in html_content or "finished" in html_content:
                        print("签到失败,你已经签到过了")
                    elif "JCoin" in html_content or "EXP" in html_content:
                        print("签到成功!")
                    else:
                        print("签到状态未知，请检查日志")

            except Exception as sign_error:
                logging.error(f"签到失败: {sign_error}", exc_info=True)
                print("签到失败，请稍后重试")

            print("自动签到执行完成！")
            print()

        except Exception as e:
            logging.error(f"JM 运行异常: {e}", exc_info=True)
