import requests
import yaml
import random
from datetime import datetime, timedelta
import json
import os
import logging
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# 简化日志输出，让最终的打印结果更清晰
logging.basicConfig(
    format='%(asctime)s %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
    level=logging.INFO)

# ☁️ 云端专属修复：时区必须改为 8，以修正 GitHub 默认的 UTC 时间
time_zone = 8  

def get_seats_with_config(user_config, date_config, seat_config):
    seat_name = date_config['name']
    if seat_name == "自定义":
        return user_config['自定义']
    return list(range(seat_config[seat_name]['begin'], seat_config[seat_name]['end']))

class SeatAutoBooker:
    def __init__(self, booker_config):
        self.user_data = None
        logging.info('初始化抢座程序...')

        # 读取账号密码 (从 GitHub Secrets 环境变量中获取)
        self.un = os.environ.get("SCHOOL_ID", "").strip()
        self.pd = os.environ.get("PASSWORD", "").strip()
        self.SCKey = os.environ.get("SCKEY", "").strip()

        chrome_options = Options()
        # ☁️ 云端专属修复：必须开启 headless（无头模式），因为云服务器没有物理显示器
        chrome_options.add_argument('--headless') 
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--window-size=1920,1080')
        # 伪装成真人电脑浏览器，防拦截
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        os.environ['WDM_LOG'] = '0' 
        
        # ☁️ 云端专属修复：GitHub 网络畅通无阻，直接使用 webdriver_manager 自动管理驱动
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        
        self.wait = WebDriverWait(self.driver, 20, 0.5)
        self.cookie = None
        self.cfg = booker_config

    def book_favorite_seat(self, user_config, seat_config):
        the_day_after_tomorrow = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][(datetime.now().weekday() + 2) % 7]
        seat_type = seat_config[user_config[the_day_after_tomorrow]['name']]["type"]
        
        if seat_type == "自习室":
            start_time = datetime.now().replace(hour=20-time_zone, minute=0, second=0, microsecond=0)
            end_time = datetime.now().replace(hour=20-time_zone, minute=15, second=0, microsecond=0)
        else:
            start_time = datetime.now().replace(hour=21-time_zone, minute=0, second=0, microsecond=0)
            end_time = datetime.now().replace(hour=21-time_zone, minute=15, second=0, microsecond=0)
            
        start_time = start_time - timedelta(minutes=self.cfg["cron-delta-minutes"])
        
        # 强行解除时间封印！无论几点都允许向服务器发包
        # if datetime.now() < start_time or datetime.now() > end_time:
        #     return -1, "未到预约时间"
            
        for tried_times in range(self.cfg["max-retry"]):
            try:
                return self._book_favorite_seat(user_config, seat_config, tried_times)
            except Exception as e:
                logging.warning(f"第 {tried_times+1} 次尝试发包失败，10秒后重试... ({e})")
                time.sleep(10)
        
        return -2, "已达到最大重试次数，预约失败"

    def _book_favorite_seat(self, user_config, seat_config, tried_times=0):
        the_day_after_tomorrow = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][(datetime.now().weekday() + 2) % 7]
        date_config = user_config[the_day_after_tomorrow]
        seats = get_seats_with_config(user_config, date_config, seat_config)
        today_0_clock = datetime.strptime(datetime.now().strftime("%Y-%m-%d 00:00:00"), "%Y-%m-%d %H:%M:%S")
        book_time = today_0_clock + timedelta(days=2) + timedelta(hours=date_config['开始时间'])
        delta = book_time - self.cfg["start-time"]
        total_seconds = delta.days * 24 * 3600 + delta.seconds
        
        # 让你在有多个自定义座位时，随机挑选一个抢（增加容错）
        seat = random.choice(seats)
        data = f"beginTime={total_seconds}&duration={3600 * date_config['持续小时数']}&&seats[0]={seat}&seatBookers[0]={self.user_data['uid']}"

        headers = self.cfg["headers"]
        headers['Cookie'] = self.cookie
        resp = requests.post(self.cfg["target"], data=data, headers=headers)
        res_json = json.loads(resp.text)
        return res_json["CODE"], res_json["MESSAGE"] + f" (尝试座位号:{seat})"

    def login(self):
        user_selector = "//input[contains(@placeholder, '学工号') or @name='username']"
        pwd_selector = "//input[@type='password']"
        btn_selector = "//button[contains(., '登录')]"

        try:
            logging.info('开始访问登录页面，请耐心等待网页完全渲染...')
            self.driver.get("https://hdu.huitu.zhishulib.com/")
            
            # 💡 强制冷静8秒，等网页画完
            time.sleep(8)
            
            # 💡 耐心拉长到60秒，要求元素可见
            super_wait = WebDriverWait(self.driver, 60, 1)
            super_wait.until(EC.visibility_of_element_located((By.XPATH, user_selector)))
            
            self.driver.find_element(By.XPATH, user_selector).send_keys(self.un)
            pwd_el = self.driver.find_element(By.XPATH, pwd_selector)
            pwd_el.send_keys(self.pd)
            
            time.sleep(1)
            pwd_el.send_keys(Keys.ENTER)
            logging.info('已提交表单，等待登录系统验证...')
            
            try:
                button = self.driver.find_element(By.XPATH, btn_selector)
                self.driver.execute_script("arguments[0].click();", button)
            except Exception:
                pass

            super_wait.until_not(EC.url_contains("sso.hdu.edu.cn"))
            super_wait.until(EC.url_contains("hdu.huitu.zhishulib.com"))
            
            time.sleep(3)
            self.cookie = ";".join([f"{c['name']}={c['value']}" for c in self.driver.get_cookies()])
            self.cfg["headers"]['Cookie'] = self.cookie
            return 0
        except Exception as e:
            self.driver.save_screenshot("error_snap.png")
            logging.error(f"网页登录过程中遇到异常，请检查 GitHub 环境。")
            return -1

    def get_user_info(self):
        headers = self.cfg["headers"]
        headers['Cookie'] = self.cookie
        # 💡 给 requests 穿上马甲，防止卡死
        headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        
        try:
            resp = requests.get("https://hdu.huitu.zhishulib.com/Seat/Index/searchSeats?LAB_JSON=1", headers=headers, timeout=15)
            try:
                res_json = resp.json()
                self.user_data = res_json['DATA']
                return 0
            except json.JSONDecodeError:
                logging.error(f"服务器未返回正确数据！前200字：{resp.text[:200]}")
                return -1
            except KeyError:
                logging.error(f"未找到 DATA 字段！完整返回：{res_json}")
                return -1
        except Exception as e:
            logging.error(f"网络请求报错: {e}")
            return -1

    def wechatNotice(self, title, desp=None):
        if self.SCKey and self.SCKey.strip() != '':
            url = f'https://sctapi.ftqq.com/{self.SCKey}.send'
            data = {'title': title, 'desp': desp}
            try:
                r = requests.post(url, data=data)
                if r.json()["data"]["error"] == 'SUCCESS':
                    logging.info("📢 Server酱微信推送成功！")
            except Exception as e:
                logging.error("推送服务调用错误。")

if __name__ == "__main__":
    print("\n" + "="*45)
    print("🚀 杭电图书馆自动抢座脚本启动 (GitHub 云端完全体)")
    print("="*45 + "\n")
    
    try:
        with open("user_config.yml", 'r', encoding='utf-8') as f: user_config = yaml.safe_load(f)
        with open("config/basic_config.yml", 'r', encoding='utf-8') as f: basic_config = yaml.safe_load(f)
        with open("config/seat_config.yml", 'r', encoding='utf-8') as f: seat_config = yaml.safe_load(f)
    except FileNotFoundError:
        print("❌ 找不到配置文件！请确保在正确的目录下运行本程序。")
        exit(-1)

    the_day_after_tomorrow = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][(datetime.now().weekday() + 2) % 7]
    
    if not user_config[the_day_after_tomorrow]['启用']:
        print(f"⏸️  配置文件中设置了 {the_day_after_tomorrow} 不抢座，程序正常退出。")
        exit(0)

    s = SeatAutoBooker(basic_config["SeatAutoBooker"])
    
    if s.login() == 0:
        print("✅ 步骤 1/3：账号登录成功！获取到有效凭证。")
        if s.get_user_info() == 0:
            print("✅ 步骤 2/3：获取个人信息成功！开始执行抢座请求...")
            
            result = s.book_favorite_seat(user_config, seat_config)
            
            if result:
                code, msg = result
                # 兼容杭电系统奇葩的 "ok" 成功代码
                if str(code) == "0" or str(code).lower() == "ok":
                    print(f"\n====================================\n🎉 最终结果: 预约成功！\n📝 详情: {msg}\n====================================\n")
                    s.wechatNotice("杭电图书馆预约成功", msg)
                elif code == -1:
                    print(f"\n====================================\n⏳ 最终结果: {msg}\n====================================\n")
                else:
                    print(f"\n====================================\n❌ 最终结果: 预约失败！\n📝 详情: {msg} (错误码: {code})\n====================================\n")
                    s.wechatNotice("杭电图书馆预约失败", f"错误码: {code}\n详细信息: {msg}")
            else:
                 print("\n====================================\n❌ 最终结果: 发生未知错误，未能返回抢座状态。\n====================================\n")
        else:
            print("\n❌ 最终结果: 步骤 2 失败 (无法获取用户信息)。")
    else:
        print("\n❌ 最终结果: 步骤 1 失败 (登录图书馆系统失败)。")

    time.sleep(3)
    s.driver.quit()
    print("🛑 程序运行结束。\n")
