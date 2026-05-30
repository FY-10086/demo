import requests
import yaml
import random
from datetime import datetime, timedelta
import json
import os
import logging

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
import time

logging.basicConfig(
    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
    level=logging.DEBUG)

time_zone = 8  # 时区

def get_seats_with_config(user_config, date_config, seat_config):
    # 二楼东/二楼西/四楼/三楼大厅/守正书院/求新书院/自定义
    seat_name = date_config['name']
    if seat_name == "自定义":
        return user_config['自定义']
    return list(range(seat_config[seat_name]['begin'], seat_config[seat_name]['end']))

class SeatAutoBooker:
    def __init__(self, booker_config):
        self.json = None
        self.resp = None
        self.user_data = None

        logging.info('Creating SeatAutoBooker object')

        # 你的账号密码（注意信息安全！）
        self.un = "23030711"  
        print("使用用户：{}".format(self.un))
        self.pd = "20050718Why"  
        
        self.SCKey = None
        try:
            self.SCKey = os.environ["SCKEY"]
        except KeyError:
            print("没有Server酱的key,将不会推送消息")

        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        
        # 自动下载匹配版本的 ChromeDriver
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        self.wait = WebDriverWait(self.driver, 10, 0.5)
        self.cookie = None

        self.cfg = booker_config

    def book_favorite_seat(self, user_config, seat_config):
        # 判断是否到了预约时间
        the_day_after_tomorrow = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][(datetime.now().weekday() + 2) % 7]
        seat_type = seat_config[user_config[the_day_after_tomorrow]['name']]["type"]
        
        if seat_type == "自习室":
            start_time = datetime.now().replace(hour=20-time_zone, minute=0, second=0, microsecond=0)
            end_time = datetime.now().replace(hour=20-time_zone, minute=15, second=0, microsecond=0)
        else:
            start_time = datetime.now().replace(hour=21-time_zone, minute=0, second=0, microsecond=0)
            end_time = datetime.now().replace(hour=21-time_zone, minute=15, second=0, microsecond=0)
            
        start_time = start_time - timedelta(minutes=self.cfg["cron-delta-minutes"])
        
        if datetime.now() < start_time or datetime.now() > end_time:
            return -1, "未到预约时间"
            
        logging.info('Booking favorite seat')
        retry_sleep_time = timedelta(minutes=self.cfg["cron-delta-minutes"]).seconds*2/(self.cfg["max-retry"]-2) - 10
        for tried_times in range(self.cfg["max-retry"]):
            try:
                return self._book_favorite_seat(user_config, seat_config, tried_times)
            except Exception as e:
                logging.exception(e)
                print(e.__class__, "尝试第{}次".format(tried_times))
                time.sleep(retry_sleep_time)

    def _book_favorite_seat(self, user_config, seat_config, tried_times=0):
        logging.info('Entering _book_favorite_seat method')
        the_day_after_tomorrow = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][(datetime.now().weekday() + 2) % 7]
        date_config = user_config[the_day_after_tomorrow]
        seats = get_seats_with_config(user_config, date_config, seat_config)
        today_0_clock = datetime.strptime(datetime.now().strftime("%Y-%m-%d 00:00:00"), "%Y-%m-%d %H:%M:%S")
        book_time = today_0_clock + timedelta(days=2) + timedelta(hours=date_config['开始时间'])
        delta = book_time - self.cfg["start-time"]
        total_seconds = delta.days * 24 * 3600 + delta.seconds
        
        if date_config['name'] == '自定义' and tried_times < self.cfg["max-retry"]/3*2:
            seat = seats[0]
        else:
            seat = random.choice(seats)
            
        data = f"beginTime={total_seconds}&duration={3600 * date_config['持续小时数']}&&seats[0]={seat}&seatBookers[0]={self.user_data['uid']}"

        headers = self.cfg["headers"]
        headers['Cookie'] = self.cookie
        print("发送请求数据:", data)
        self.resp = requests.post(self.cfg["target"], data=data, headers=headers)
        self.json = json.loads(self.resp.text)
        return self.json["CODE"], self.json["MESSAGE"] + " 座位:{}".format(seat)

    def login(self):
        logging.info('Login in')

        # 兼容性更强的 XPath
        user_path_selector = """//input[@placeholder='请输入学工号/绑定手机/证件号' or @name='username']"""
        pwd_path_selector = """//input[@type='password']"""
        button_path_selector = """//button[@type='submit']"""

        try:
            logging.info('开始登陆...')
            self.driver.get("https://hdu.huitu.zhishulib.com/")
            logging.debug('打开网站.')

            long_wait = WebDriverWait(self.driver, 30, 0.5)

            long_wait.until(EC.presence_of_element_located((By.XPATH, user_path_selector)))
            logging.debug('找到用户名输入框.')

            long_wait.until(EC.presence_of_element_located((By.XPATH, pwd_path_selector)))
            logging.debug('找到密码输入框.')

            long_wait.until(EC.presence_of_element_located((By.XPATH, button_path_selector)))
            logging.debug('找到登录按钮.')

            self.driver.find_element(By.XPATH, user_path_selector).clear()
            self.driver.find_element(By.XPATH, user_path_selector).send_keys(self.un) 
            logging.info('输入用户名')

            self.driver.find_element(By.XPATH, pwd_path_selector).clear()
            self.driver.find_element(By.XPATH, pwd_path_selector).send_keys(self.pd)  
            logging.info('输入密码')
            
            logging.info('点击登录按钮')
            time.sleep(1)  # 稍微停顿，模拟人类操作节奏
            self.driver.find_element(By.XPATH, button_path_selector).click()
            
            # 🚨 最关键的 SSO 跳转等待逻辑
            logging.info('等待系统校验并跳出 SSO 统一认证中心...')
            # 必须等到网址里彻底没有 sso 这个词
            long_wait.until_not(EC.url_contains("sso.hdu.edu.cn"))
            
            logging.info('等待完全回到图书馆主页...')
            # 必须等到网址变回图书馆域名
            long_wait.until(EC.url_contains("hdu.huitu.zhishulib.com"))
            
            # 跳转成功后，给网页 3 秒钟时间彻底把 Cookie 写进浏览器
            time.sleep(3)
            
            cookie_list = self.driver.get_cookies()
            self.cookie = ";".join([item["name"] + "=" + item["value"] + "" for item in cookie_list])
            self.cfg["headers"]['Cookie'] = self.cookie

            logging.info("登录成功！获取到真实 Cookie。")
        except Exception as e:
            logging.error(f"登录失败：{e}")
            try:
                self.driver.save_screenshot("error_snap.png")
                logging.info("📸 已经拍下当前浏览器的画面，保存在代码同级目录的 error_snap.png 中！")
            except Exception as snap_e:
                logging.error(f"截图失败: {snap_e}")
            return -1
        return 0

    def get_user_info(self):
        logging.info('Getting user info')

        headers = self.cfg["headers"]
        headers['Cookie'] = self.cookie
        try:
            resp = requests.get("https://hdu.huitu.zhishulib.com/Seat/Index/searchSeats?LAB_JSON=1",
                                headers=headers)
            self.user_data = resp.json()['DATA']
            _ = self.user_data['uid']
        except Exception as e:
            logging.exception(e)
            print(self.user_data)
            print(e.__class__.__name__ + ",获取用户数据失败")
            return -1
        print("获取用户数据成功")
        return 0

    def wechatNotice(self, message, desp=None):
        logging.info('Sending WeChat notice')

        if self.SCKey != '':
            url = 'https://sctapi.ftqq.com/{0}.send'.format(self.SCKey)
            data = {
                'title': message,
                'desp': desp,
            }
            try:
                r = requests.post(url, data=data)
                if r.json()["data"]["error"] == 'SUCCESS':
                    print("Server酱通知成功")
                else:
                    print("Server酱通知失败")
            except Exception as e:
                logging.exception(e)
                print(e.__class__, "推送服务配置错误")

def is_booking_enable(date_cfg):
    if date_cfg['启用']:
        return True
    return False

if __name__ == "__main__":
    logging.info('Start of the program')
    
    # 解决 Windows 下中文配置文件读取乱码的问题
    with open("user_config.yml", 'r', encoding='utf-8') as f_obj:
        user_config = yaml.safe_load(f_obj)
    with open("config/basic_config.yml", 'r', encoding='utf-8') as f_obj:
        basic_config = yaml.safe_load(f_obj)
    with open("config/seat_config.yml", 'r', encoding='utf-8') as f_obj:
        seat_config = yaml.safe_load(f_obj)

    the_day_after_tomorrow = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][(datetime.now().weekday() + 2) % 7]
    
    if not is_booking_enable(user_config[the_day_after_tomorrow]):
        logging.info('预约未启用')
        print("预约未启用")
        exit(0)

    s = SeatAutoBooker(basic_config["SeatAutoBooker"])
    if not s.login() == 0:
        s.driver.quit()
        logging.info('Login unsuccessful')
        exit(-1)
        
    if not s.get_user_info() == 0:
        s.driver.quit()
        logging.info('Getting user info unsuccessful')
        exit(-1)
        
    s.book_favorite_seat(user_config=user_config, seat_config=seat_config)
    s.driver.quit()
    logging.info('End of the program')
