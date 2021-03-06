# -*- coding:utf-8 -*-
import time
import os
import requests
import ctypes
import sys


# 检查是否有管理员权限
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


# 因为需要杀死其他进程，所以本脚本需要在管理员权限下运行
if not is_admin():
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, __file__, None, 1)
    sys.exit(0)

# ========================================
'''
#1 定时检测网络连接情况（pingbaidu）
#2 若无法联网，进行一小段时间的多次确认（尝试等待恢复）
#3 若无法恢复联网，杀死客户端并依照已重启次数延时重启
#4 重启后，记录重启次数，回到#2

所有事件都写入日志
    日志分为信息和错误
'''

# ping_test的几种返回值
ONLINE = 0
UNLOGIN = 1
OFFLINE = 2
ERROR = 3

# 使输出到命令行
PRINT = True


# TODO: 增加预定监视时长，而不仅仅是监视次数n

class Supervisor:
    # 初始化
    def __init__(self, n=1440, every=60, log_file="E:/log.txt", verbose=False):
        self.n = n  # 每次运行本程序监视次数
        self.every = every  # 重连检查时间间隔秒数，不要太短
        self.log_file = log_file  # 日志文件绝对路径，例如："E:/log.txt"
        self.verbose = verbose  # 置True可将所有日志信息同时打印到命令行

        self.__client_dir = r"C:\Drcom\DrUpdateClient\DrMain.exe"
        self.__restart = 12  # 重启软件等待联网秒数，由试验得出最短12秒
        self.__test_url = "http://www.baidu.com"
        self.__test_url_label = 'baidu'  # 如果ping到了会出现这个字符，而如果被dns劫持则不会出现这个字符

    # 写日志
    def log(self, str_, print_=None):
        if not (print_ is None and not self.verbose):  # 默认情况下由self.verbose控制命令行输出
            print(self.get_time() + " " + str_)
        with open(self.log_file, "a") as f:
            f.write(self.get_time() + " " + str_ + "\n")

    # 获取时间字符串。运行增加指定秒数的偏移
    @staticmethod
    def get_time(offset=0):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + offset))

    # 尝试ping一个测试网址（默认baidu），判断当前是否可以连网
    def ping_test(self):
        try:
            q = requests.get(self.__test_url)
            if q.status_code == 200:
                if self.__test_url_label in q.url:
                    self.log("已连接到互联网")
                    return ONLINE
                else:
                    self.log("无法连接到互联网（外网）")
                    return UNLOGIN
            else:
                self.log("网线已断开", PRINT)
                return OFFLINE
        except Exception as e:
            self.log("请求异常: " + e.args[0], PRINT)
            return ERROR

    # 重新启动客户端:重启 = 杀死+启动
    # 耗时14秒
    def restart(self):
        os.system("taskkill /F /IM DrMain.exe")
        os.system("taskkill /F /IM DrClient.exe")
        os.system("taskkill /F /IM DrUpdate.exe")
        time.sleep(2)  # 为了保障系统完成杀进程操作所必须的时间

        self.log("正在重启客户端...", PRINT)
        os.startfile(self.__client_dir)
        time.sleep(self.__restart)  # 为了保证正常重启生效所必须的最小时间

    # 延迟重试
    # 耗时  t*(t+1)/2 * b + 14*times  (默认34秒)
    def delay_test(self, times=1, basic_delay=20, requirement=None):
        """
        参考开发文件：流程图.drawio
        :param times: 重试次数上限，默认试一次
        :param basic_delay: 基本延迟时间，默认20秒，重试第n次会实际延迟basic_delay*n秒
        :param requirement:list 需求条件，当ping_test输出状态码为含于其中时成功
        :return: 超过重试次数上限仍未出现含于requirement的状态码则None，否则为状态码
        """
        if requirement is None:
            requirement = [ONLINE]
        n = 0
        while n <= times:
            n += 1
            delay = basic_delay * n
            self.log('第{}次延迟重试将在 '.format(n) + self.get_time(delay) + ' ({}秒后)开始'.format(delay), PRINT)
            time.sleep(delay)  # 启动本函数时说明已经出问题了，应该先延迟再重试
            self.log('正在重启客户端...', PRINT)
            self.restart()
            flag = self.ping_test()
            if flag in requirement:
                return flag
        return None

    # 延迟重试需要一个封装来实现递归逻辑
    def recovering(self, flag):
        if flag == UNLOGIN:  # 无法连接到互联网（外网）
            recover = self.delay_test(5)  # 重试5次（总耗时最多370秒）
            if recover == ONLINE:
                self.log('延迟重启成功')
                return True
            else:
                self.log('延迟重启失败')
                return False

        elif flag == OFFLINE:  # 网线已断开
            recover = self.delay_test(2, 40, [ONLINE, UNLOGIN])  # 重试2次（总耗时最多162秒）
            if recover == ONLINE:
                self.log('延迟重启成功')
                return True
            elif recover == UNLOGIN:
                # 递归到1
                self.recovering(recover)
            else:
                self.log('延迟重启失败')
                return False

        elif flag == ERROR:  # 未知异常
            recover = self.delay_test(1, 60, [ONLINE, UNLOGIN])  # 重试1次（总耗时最多74秒）
            if recover == ONLINE:
                self.log('延迟重启成功')
                return True
            elif recover == UNLOGIN:
                # 递归到1
                self.recovering(recover)
            else:
                self.log('延迟重启失败')
                return False

    # 最外层的监视
    def watch(self):
        self.log('启动watch', PRINT)
        count = 0
        while count <= self.n:
            count += 1
            flag = self.ping_test()
            if flag != ONLINE and not self.recovering(flag):
                self.log('延迟重试超时，退出watch', PRINT)
                return False
            else:
                time.sleep(sv.every)

        self.log('达到预定监视次数，退出watch', PRINT)
        return True


# ------------------------------------
sv = Supervisor()

# 测试模式
sv.verbose = True
sv.every = 10
sv.n = 10

sv.watch()
