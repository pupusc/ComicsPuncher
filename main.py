import logging
import os
from pica_punch import PicaPuncher
from jm_punch import JmPuncher

# 日志格式设置
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- 用户配置区 ---
# 优先从环境变量读取 (用于 GitHub Actions)，否则使用默认值
PICA_USER = os.getenv("PICA_USER")
PICA_PW = os.getenv("PICA_PW")

JM_USER = os.getenv("JM_USER")
JM_PW = os.getenv("JM_PW")

MY_PROXY = os.getenv("MY_PROXY", "")  # 例如 "127.0.0.1:7890"
# ----------------

if __name__ == "__main__":
    logging.info("=" * 50)
    logging.info("🚀 ComicsPuncher 启动")
    logging.info("=" * 50)
    
    # 检查配置
    if not all([PICA_USER, PICA_PW, JM_USER, JM_PW]):
        logging.error("❌ 请配置完整的账号信息！")
        exit(1)
    
    # 执行哔咔打卡
    pica = PicaPuncher(PICA_USER, PICA_PW, MY_PROXY)
    pica.run()

    # 执行 JM 打卡
    jm = JmPuncher(JM_USER, JM_PW, MY_PROXY)
    jm.run()
    
    logging.info("=" * 50)
    logging.info("✅ 所有任务执行完毕")
    logging.info("=" * 50)
