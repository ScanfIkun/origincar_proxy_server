"""
上位坤（爆改版） v1.0.0 🚀 MIT License - https://mit-license.org/
   ___      _    __         ____                    
  / _ )____(_)__/ /__ ____ / __/__ _____  _____ ____
 / _  / __/ / _  / _ `/ -_)\ \/ -_) __/ |/ / -_) __/
/____/_/ /_/\_,_/\_, /\__/___/\__/_/  |___/\__/_/   
                /___/       HFUT - 洛圣都改车王      
使用方法：
1. OriginCar分别运行下面四条命令
   ros2 run spfs_pkg_python start
   ros2 launch origincar_bringup camera.launch.py
   ros2 launch origincar_base origincar_bringup.launch.py
   ros2 launch rosbridge_server rosbridge_websocket_launch.xml
2. coStudio连接至localhost:9090
3. 按下键盘 [ r ] 控制小车
提示：
1. 本程序启动后无需操作
2. 本程序的配置文件是./common/config.json
"""

import asyncio
import websockets
import json
import logging
import time
import base64
import numpy as np

from rosmsg_tools import RosmsgTools,RosTopic
from openaidemo import scan

from threading import Thread
import keyboard

# #ORIGINCAR_ADDRESS = "wss://ws.postman-echo.com/raw" # 测试服务器
# #ORIGINCAR_ADDRESS = "ws://localhost:8765"
# ORIGINCAR_ADDRESS = "ws://192.168.2.105:9090"

class BridgeServer():
    PROXY_HOST: str
    PROXY_PORT: int
    MEDIA_ADDRESS: str
    TARGET_ADDRESS: str
    SPEED_1: list[int]
    SPEED_2: list[int]
    SPEED_3: list[int]
    SPEED_4: list[int]
    TPF_TARGET: int
    LEVEL_MAX: int
    TYPES: dict[str, list[str]]
    
    def __init__(self):
        # 文档
        print(__doc__)

        # 日志模块
        self.logger = logging.getLogger()

        # 话题和配置文件
        self.RosmsgTools=RosmsgTools()
        self.topics:dict[str,RosTopic]={}

        # 创建事件循环
        self.clientConnected=asyncio.Event()
        self.mediaConnected=asyncio.Event()
        self.targetConnected=asyncio.Event()
        self.EventLoop=asyncio.get_event_loop()
        self.ProxyServe=ProxyServe(self)
        self.TargetConnect=TargetConnect(self)
        self.MediaConnect=MediaConnect(self)
        self.KeyboardListener=KeyboardListener(self)# 键盘模块

        # 启动服务
        self.start()

    def start(self):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        types=self.TYPES
        for index,item in enumerate(types['topics']):
            self.topics[item]=self.RosmsgTools.getTopic(item,types['types'][index],types['typedefs_full_text'][index])
        self.EventLoop.run_forever()


    async def pub_text(self,message:str):
        topic=self.topics["/proxy/msgout"]
        res=topic.serialize({"data":message})
        await self.toClient(res)
    
    async def pub_map(self):
        with open("./common/map.b64",'r') as f:
            msg=f.read()
        await self.toClient(base64.b64decode(msg))
        self.logger.info("发送地图成功")

    async def pub_video(self,message,height,width,step):
        ras=self.RosmsgTools.img_serialize(message,height,width,step)
        await self.toClient(ras)

    async def act_video(self):
        if not self.MediaConnect.active.is_set():
            self.MediaConnect.active.set()
        #await self.toMedia("start")

    async def get_speed(self) -> tuple[bool,float,float]:
        return self.KeyboardListener.listenEnable,self.KeyboardListener.linear,self.KeyboardListener.angular
    
    async def get_rsp(self,message:dict) -> dict:
        for item in self.topics.values():
            message['values']['topics'].append(item.name)
            message['values']['types'].append(item.type)
            message['values']['typedefs_full_text'].append(item.typedef)
        return message
    
    async def pause_keyboard(self):
        self.KeyboardListener.toStop=True
    
    async def offline(self) -> None:
        if self.TargetConnect.server:
            await self.TargetConnect.server.close()
            self.TargetConnect.server=None
            self.targetConnected.clear()
        if self.MediaConnect.server:
            await self.MediaConnect.server.close()
            self.MediaConnect.server=None
            self.mediaConnected.clear()
        self.logger.info("已断开Media,Target连接")

    async def clear_client(self):
        if self.ProxyServe.client:
            await self.ProxyServe.client.close()
            await self.ProxyServe.client.wait_closed()
            self.ProxyServe.client=None
            self.clientConnected.clear()
        self.logger.info("已关闭client连接")

    async def stop_proxy(self):
        if self.ProxyServe.client:
            pass
        if self.ProxyServe.server:
            self.ProxyServe.server.close()
            await self.ProxyServe.server.wait_closed()
            self.ProxyServe.server=None
            self.logger.info("已关闭proxy服务器")
    
    async def toTarget(self,message:dict):
        try:
            await self.targetConnected.wait()
            await self.TargetConnect.server.send(json.dumps(message))
        except:
            self.logger.info("发送失败，可能是Target已经断开连接")

    async def toClient(self,message:bytes|str):
        try:
            await self.ProxyServe.client.send(message)
        except:
            if self.ProxyServe.client:
                await self.offline()
                await self.ProxyServe.client.close()
                self.ProxyServe.client=None
                self.clientConnected.clear()
                self.logger.info("已断开client连接")

    async def toMedia(self,message):
        await self.mediaConnected.wait()
        await self.MediaConnect.server.send(message)

    async def model_run(self):
        self.MediaConnect.img_get.clear()
        await self.MediaConnect.img_get.wait()
        cv2.imwrite('output_opencv.jpg',self.MediaConnect.img_temp)
        text=await self.EventLoop.run_in_executor(None, scan,'output_opencv.jpg')
        topic=self.topics["/proxy/ai"]
        res=topic.serialize({"data":text})
        await self.toClient(res)
        return



class TargetConnect():
    """
    连接至目标服务器
    """
    def __init__(self,root:BridgeServer) -> None:
        self.server=None
        self.logger=logging.getLogger("TargetConnect")
        
        # 继承父方法和变量
        self.toClient:function=root.toClient
        self.pub_map:function=root.pub_map
        self.get_rsp:function=root.get_rsp
        self.stop_proxy:function=root.stop_proxy
        self.targetConnected=root.targetConnected
        self.clientConnected=root.clientConnected
        
        # 创建任务
        root.EventLoop.create_task(self.start())

    async def start(self):
        retry=0
        while True:
            if retry<10:
                self.logger.info("正在连接Target服务器")
            try:
                async with websockets.connect(BridgeServer.TARGET_ADDRESS) as self.server:
                    self.targetConnected.set()
                    self.logger.info("Target服务器连接成功")
                    async for message in self.server:
                        await self.handler(message)
            except:
                retry+=1
                if retry<10:
                    self.logger.info("正在尝试重新连接Target服务器...")
                self.targetConnected.clear()
                await self.stop_proxy()
                await asyncio.sleep(2)

    async def handler(self,msg):
        if type(msg)==str:
            message=json.loads(msg)
            await getattr(self,f"{message['op']}_callback",self.default_callback)(message)
        elif type(msg)==bytes:
            await self.toClient(msg)
        else:
            await self.toClient(msg)
            self.logger.info(f"收到未知信息：{message}")

    async def default_callback(self,message):
        await self.toClient(message)

    async def service_response_callback(self,message:dict):
        if message['service']=="/rosapi/topics_and_raw_types":
            message=await self.get_rsp(message)
        await self.toClient(json.dumps(message))



class ProxyServe():
    """
    监听本地客户端消息
    """
    def __init__(self,root:BridgeServer) -> None:
        self.client=None
        self.server=None
        self.logger=logging.getLogger("ProxyServe")
        # 继承父方法
        # for method in ('toTarget', 'pub_map', 'pub_text', 'model_run', 'act_video'):
        #     setattr(self, method, getattr(root, method))
        self.toTarget:function=root.toTarget
        self.toClient:function=root.toClient
        self.pub_map:function=root.pub_map
        self.pub_text:function=root.pub_text
        self.model_run:function=root.model_run
        self.act_video:function=root.act_video
        self.clear_client:function=root.clear_client
        self.offline:function=root.offline
        self.pause_keyboard:function=root.pause_keyboard
        self.clientConnected=root.clientConnected
        self.targetConnected=root.targetConnected
        self.topics=root.topics
        # 创建任务
        root.EventLoop.create_task(self.start())

    async def start(self):
        while True:
            await self.targetConnected.wait()
            async with websockets.serve(self.handler,BridgeServer.PROXY_HOST,BridgeServer.PROXY_PORT) as self.server:
                await self.server.wait_closed()

    async def handler(self,websocket):
        if not self.client:
            self.client=websocket
            self.clientConnected.set()
            self.logger.info("client 已连接")
            async for msg in self.client:
                message=json.loads(msg)
                await getattr(self,f"{message['op']}_callback",self.default_callback)(message)
            self.clientConnected.clear()
            self.client=None
            await self.offline()
            self.logger.info("client 断开连接")
        else:
            await self.clear_client()

    async def default_callback(self,message):
        await self.toTarget(message)

    async def publish_callback(self,message):
        topic=message['topic'][1:]
        await getattr(self,f"topic_on_{topic}",self.topic_on_default)(message)
        await self.toTarget(message)

    async def topic_on_default(self,message:dict):
        pass

    async def topic_on_sign4return(self,message:dict):
        if message['msg']['data']==12:
            await self.pub_map()
            await self.act_video()
        elif message['msg']['data']==11:
            self.logger.info("大模型识别")
            await self.pub_text(f"大模型识别中{time.time()}")
            await self.model_run()
            await self.pub_text(f"大模型识别完成{time.time()}")
        elif message['msg']['data']==6:
            await self.pub_text(f"C区结束遥测{time.time()}")
            await self.pause_keyboard()

    async def subscribe_callback(self,message):
        topic=message['topic']
        if topic in self.topics:
            pass
        else:
            await self.toTarget(message)


import cv2
class MediaConnect():
    """
    连接至媒体源
    """
    def __init__(self,root:BridgeServer) -> None:
        self.server=None
        self.active=asyncio.Event()
        self.logger=logging.getLogger("MediaConnect")
        # 业务逻辑
        self.img_temp=None
        self.img_get=asyncio.Event()
        self.last_time:float=time.time()
        self.img_tps:int=root.TPF_TARGET
        self.img_level:int=root.LEVEL_MAX
        # 继承父对象方法
        self.pub_video:function=root.pub_video
        self.get_speed:function=root.get_speed
        self.mediaConnected=root.mediaConnected
        self.clientConnected=root.clientConnected
        self.targetConnected=root.targetConnected
        # 创建任务
        root.EventLoop.create_task(self.start())

    async def start(self):
        retry=0
        self.active.set()
        while True:
            await self.active.wait()
            await self.clientConnected.wait()
            self.logger.info("正在连接Media服务器")
            try:
                async with websockets.connect(BridgeServer.MEDIA_ADDRESS) as self.server:
                    if self.clientConnected.is_set():
                        retry=0
                        self.logger.info("Media服务器连接成功")
                        self.mediaConnected.set()
                        await self.server.send("start")
                        async for message in self.server:
                            await self.handler(message)
                    else:
                        self.logger.info("断开Media服务器连接，因为client未连接")
                        raise RuntimeError("client not connected")
            except:
                retry+=1
                if retry>5:
                    self.active.clear()
                    self.logger.info("Media服务器连接中断")
                else:
                    self.logger.info(f"Media服务器连接中断，{retry*2}秒后尝试重新连接...")
                    await asyncio.sleep(retry*2)
                if self.targetConnected.is_set():
                    await self.pub_nosignal()
                self.mediaConnected.clear()

    async def handler(self,message):
        time_last=self.last_time
        self.last_time=time.time()
        dt=self.last_time-time_last

        self.img_level+=int((self.img_tps-dt*1000)/10)
        self.img_level=max(min(self.img_level,BridgeServer.LEVEL_MAX),1)

        nparr = np.frombuffer(message , np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        h,w,d=img.shape
        if not self.img_get.is_set():
            self.img_temp=img.copy()
            self.img_get.set()
        e,l,a = await self.get_speed()
        if e:
            cv2.putText(img,f"SPEED:{l:.2f}m/s,{a:.2f}rad", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(img,f"TPF:{int(dt*1000)}ms", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(img,f"LEVEL:{self.img_level}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
            
            cv2.line(img, (int(w*135/640),h), (int(w*284/640),int(h*195/360)), (0, 255, 255), 2)
            cv2.line(img, (int(w*520/640),h), (int(w*375/640),int(h*195/360)), (0, 255, 255), 2)
            cv2.line(img, (int(w*328/640),h), (int(w*328/640),h-10), (0, 255, 255), 1)
            cv2.putText(img,f"40cm",(int(w*375/640),int(h*195/360)), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(img,f"20cm",(int(w*410/640),int(h*235/360)), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(img,f"10cm",(int(w*460/640),int(h*291/360)), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(img,f"5cm",(int(w*514/640),int(h*354/360)), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 255, 255), 1, cv2.LINE_AA)
        else:
            cv2.putText(img,f"TPF:{int(dt*1000)}ms", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(img,f"LEVEL:{self.img_level}", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)

        #height=360, width=640, encoding='jpeg', is_bigendian=0, step=1920
        await self.pub_video(img.flatten(order='C') ,h,w,w*d)
        await self.server.send(str(self.img_level))
        return None
        cv2.imwrite('output_opencv.jpg', img)

    async def pub_nosignal(self):
        with open('./common/nosignal.png', 'rb') as f:
            img=cv2.imdecode(np.frombuffer(f.read(), dtype=np.uint8), cv2.IMREAD_COLOR)
        h,w,d=img.shape
        await self.pub_video(img.flatten(order='C') ,h,w,w*d)


class KeyboardListener():
    """
    监听键盘
    """
    def __init__(self,root:BridgeServer):
        self.linear = root.SPEED_2[0]
        self.angular = root.SPEED_2[1]
        self.dert = 0.1

        self.toTarget:function=root.toTarget
        self.pub_text:function=root.pub_text
        self.model_run:function=root.model_run
        self.model_future=None
        self.targetConnected=root.targetConnected
        self.logger=logging.getLogger("KeyboardListener")
        self.loop=root.EventLoop

        self.start_time:float=time.time()
        self.counter=0
        self.toStop=False
        self.listenEnable:bool=False
        self.start()

    def start(self):
        self.keyboard_thread=Thread(target=self.keyboard_listener,daemon=True)
        self.keyboard_thread.start()

    def out_text(self,message:str):
        f=asyncio.run_coroutine_threadsafe(self.pub_text(message),self.loop)
        f.result()
        #self.loop.call_soon_threadsafe(asyncio.create_task,self.pub_text(message))

    def out_cmd(self,message:dict):
        try:
            f=asyncio.run_coroutine_threadsafe(self.toTarget(message),self.loop)
            f.result()
        except:
            self.logger.info(f"toTarget出错")
        #self.loop.call_soon_threadsafe(asyncio.create_task,self.toTarget(message))
            
    def run_model(self):
        if self.model_future is None:
            self.logger.info("大模型识别(快捷键施法)")
            self.out_text(f"大模型识别中(快捷键施法){time.time()}")
            self.model_future=asyncio.run_coroutine_threadsafe(self.model_run(),self.loop)
        if self.model_future.done():
            self.model_future=None

    def pub_keymap(self,key:str):
        keymap = {
            'up'         : {'linear': {'x': self.linear,'y': 0.0,    'z': 0.0           },
                           'angular': {'x': 0.0,        'y': 0.0,    'z': 0.0          }},
            'down'       : {'linear': {'x':-self.linear,'y': 0.0,    'z': 0.0           },
                           'angular': {'x': 0.0,        'y': 0.0,    'z': 0.0          }},
            'left'       : {'linear': {'x': 0.0,        'y': 0.0,    'z': 0.0           },
                           'angular': {'x': 0.0,        'y': 0.0,    'z': self.angular }},
            'right'      : {'linear': {'x': 0.0,        'y': 0.0,    'z': 0.0           },
                           'angular': {'x': 0.0,        'y': 0.0,    'z':-self.angular }},
            'up_left'    : {'linear': {'x': self.linear,'y': 0.0,    'z': 0.0           },
                           'angular': {'x': 0.0,        'y': 0.0,    'z': self.angular }},
            'up_right'   : {'linear': {'x': self.linear,'y': 0.0,    'z': 0.0           },
                           'angular': {'x': 0.0,        'y': 0.0,    'z':-self.angular }},
            'down_left'  : {'linear': {'x':-self.linear,'y': 0.0,    'z': 0.0           },
                           'angular': {'x': 0.0,        'y': 0.0,    'z': self.angular }},
            'down_right' : {'linear': {'x':-self.linear,'y': 0.0,    'z': 0.0           },
                           'angular': {'x': 0.0,        'y': 0.0,    'z':-self.angular }},
            'stop'       : {'linear': {'x': 0.0,        'y': 0.0,    'z': 0.0           },
                           'angular': {'x': 0.0,        'y': 0.0,    'z': 0.0          }}
        }[key]
        self.counter+=1
        self.out_cmd({
            "op": "publish",
            "id":f"proxy_publish:/cmd_vel:{self.counter}",
            "topic":"/cmd_vel",
            "msg":keymap,
            "latch": False
        })

    def pub_signal(self,signal:int):
        self.counter+=1
        self.out_cmd({
            "op": "publish",
            "id":f"proxy_publish:/sign4return:{self.counter}",
            "topic":"/sign4return",
            "msg":{"data":signal},
            "latch": False
        })

    def keyboard_listener(self):
        while True:
            while True:
                time.sleep(0.05)
                self.listenEnable=False
                if keyboard.is_pressed('r'):
                    self.start_time=time.time()
                    self.help_tip()
                    self.logger.info("正在继续键盘监听.")
                    break
            while True:
                time.sleep(0.05)
                self.listenEnable=True

                if keyboard.is_pressed('p') or self.toStop or (not self.targetConnected.is_set()):# 退出激活键盘控制
                    self.pub_keymap('stop')
                    dt=time.time()-self.start_time
                    star="⭐"*(5-int(dt/5))
                    self.out_text(f"已退出键盘监听\n本次用时{dt:.2f}s\n{star}")
                    self.logger.info("已退出键盘监听,按下[ r ]继续键盘监听")
                    self.toStop=False
                    break

                if keyboard.is_pressed('esc'):
                    self.pub_signal(6)
                    self.toStop=True
                elif keyboard.is_pressed('e'):
                    self.run_model()
                elif keyboard.is_pressed('1'):
                    self.linear=BridgeServer.SPEED_1[0]
                    self.angular=BridgeServer.SPEED_1[1]
                    self.out_text(f"一档:{self.linear:.2f}m/s,{self.angular:.2f}rad")
                elif keyboard.is_pressed('2'):
                    self.linear=BridgeServer.SPEED_2[0]
                    self.angular=BridgeServer.SPEED_2[1]
                    self.out_text(f"二档:{self.linear:.2f}m/s,{self.angular:.2f}rad")
                elif keyboard.is_pressed('3'):
                    self.linear=BridgeServer.SPEED_3[0]
                    self.angular=BridgeServer.SPEED_3[1]
                    self.out_text(f"三档:{self.linear:.2f}m/s,{self.angular:.2f}rad")
                elif keyboard.is_pressed('4'):
                    self.linear=BridgeServer.SPEED_4[0]
                    self.angular=BridgeServer.SPEED_4[1]
                    self.out_text(f"四档:{self.linear:.2f}m/s,{self.angular:.2f}rad")
                elif keyboard.is_pressed('w'):                                  # 前进
                    if keyboard.is_pressed('a'):                              # 前进加左转
                        self.pub_keymap('up_left')
                    elif keyboard.is_pressed('d'):                            # 前进加右转
                        self.pub_keymap('up_right')
                    else:
                        self.pub_keymap('up')
                elif keyboard.is_pressed('s'):                                # 后退
                    if keyboard.is_pressed('d'):                              # 后退加左转
                        self.pub_keymap('down_left')
                    elif keyboard.is_pressed('a'):                            # 后退加右转
                        self.pub_keymap('down_right')
                    else:
                        self.pub_keymap('down')
                elif keyboard.is_pressed('a'):                                # 仅左转
                    self.pub_keymap('left')
                elif keyboard.is_pressed('d'):                                # 仅右转
                    self.pub_keymap('right')

                elif keyboard.is_pressed("up"):
                    self.linear += self.dert
                    self.out_text("线速度设置为:{:.2f}m/s.".format(self.linear))
                    time.sleep(0.2)
                elif keyboard.is_pressed("down"):
                    if self.linear - self.dert < 0:
                        self.out_text("速度设置失败！(线速度为:{:.2f}).".format(self.linear))
                    else:
                        self.linear -= self.dert
                        self.out_text("线速度设置为:{:.2f}m/s.".format(self.linear))
                    time.sleep(0.2)
                elif keyboard.is_pressed("left"):
                    if self.angular - self.dert < 0:
                        self.out_text("角度设置失败！(转角为:{:.2f}rad).".format(self.angular))
                    else:
                        self.angular -= self.dert
                        self.out_text("角度设置为:{:.2f}rad.".format(self.angular))
                    time.sleep(0.2)
                elif keyboard.is_pressed("right"):
                    self.angular += self.dert
                    self.out_text("转角设置为:{:.2f}rad.".format(self.angular))
                    time.sleep(0.2)

                elif keyboard.is_pressed('t'):
                    self.help_tip()
                    time.sleep(0.5)
                elif keyboard.is_pressed('-'):
                    self.pub_signal(100)
                    time.sleep(0.5)
                elif keyboard.is_pressed('+'):
                    self.pub_signal(101)
                    time.sleep(0.5)
                elif keyboard.is_pressed('9'):
                    self.pub_signal(103)
                    time.sleep(0.5)
                elif keyboard.is_pressed('*'):
                    self.pub_signal(200)
                    time.sleep(0.5)
                else:
                    self.pub_keymap('stop')

    def help_tip(self):
        tip=f"""
提示：
按   [ p ] 退出键盘控制.
按   [ r ] 回到键盘控制.
按   [ t ] 显示按键帮助.
按   [ e ] 大模型识别.
按   [esc] c区出口结束遥测.

控制：
--- [ w ] --- 前进: {self.linear:.2f} m/s.
--- [ a ] --- 左转: {self.angular:.2f} rad.
--- [ d ] --- 右转: {-self.angular:.2f} rad.
--- [ s ] --- 后退: {-self.linear:.2f} m/s.
调整速度(使用键盘的方向键).
---  [   up  ]  --- 增加线速度.
---  [  left ]  --- 减小转角.
---  [ right ]  --- 增加转角.
---  [  down ]  --- 减小线速度.
---  [   1   ]  --- 前进一.
---  [   2   ]  --- 前进二.
---  [   3   ]  --- 前进三.
---  [   4   ]  --- 前进四.
"""
        self.out_text(tip)

if __name__ == "__main__":
    """
    编译：
    cd .\cost\pack
    python -m PyInstaller -i linux.ico -F origincar_proxy_server.py --hidden-import rosbags.typesys.stores.ros2_foxy --hidden-import rosbags.serde.primitives
    导出依赖:
    pip freeze > requirements.txt
    注意:
    打包前需要去除掉os.chdir(os.path.dirname(__file__))这行代码
    costudio开启调试
    --inspect --remote-debugging-port --remote-allow-origins=*
    """
    #import os
    #os.chdir(os.path.dirname(__file__))
    with open("./common/config.json",'r') as f:
        temp=json.load(f)
        BridgeServer.TYPES=temp['values']
        BridgeServer.PROXY_HOST=temp['proxy_host']
        BridgeServer.PROXY_PORT=temp['proxy_port']
        BridgeServer.MEDIA_ADDRESS=temp['media_address']
        BridgeServer.TARGET_ADDRESS=temp['target_address']
        BridgeServer.SPEED_1=temp['speed_1']
        BridgeServer.SPEED_2=temp['speed_2']
        BridgeServer.SPEED_3=temp['speed_3']
        BridgeServer.SPEED_4=temp['speed_4']
        BridgeServer.TPF_TARGET=temp['tpf_target']
        BridgeServer.LEVEL_MAX=temp['level_max']
    app = BridgeServer()