from rosbags.typesys import Stores, get_typestore
from rosbags.typesys.msg import get_types_from_msg
import cbor2,base64
import time

class RosTopic():
    def __init__(self,tools,name:str,type:str,typedef:str=None) -> None:
        self.name=name
        self.type=type
        self.typedef=typedef
        self.tools=tools
    def serialize(self,obj:dict) -> bytes:
        nowtime=time.time()
        temp={
            'op':"publish",
            'topic':self.name,
            'msg':{
                'secs':int(nowtime),
                'nescs':int(nowtime%1*10000000),
                'bytes':obj
            }
        }
        return self.tools.serialize(temp,self.type)

    def deserialize(self,hex:bytes) -> dict:
        res=self.tools.buffer2obj(hex,self.type)
        return res

class RosmsgTools():
    def __init__(self):
        self.typestore = get_typestore(Stores.ROS2_FOXY)

    def img_serialize(self,img,height,width,step):
        nowtime=time.time()
        header={
                "stamp":self.typestore.types["builtin_interfaces/msg/Time"](**{"sec":0,"nanosec":0}),
                "frame_id":""
        }
        bit={
            "header":self.typestore.types["std_msgs/msg/Header"](**header),
            "height":height,
            "width":width,
            "encoding":"bgr8",
            "is_bigendian":0,
            "step":step,
            "data":img,
        }
        temp={
            'op':"publish",
            'topic':"/proxy/image",
            'msg':{
                'secs':int(nowtime),
                'nescs':int(nowtime%1*10000000),
                'bytes':bytes(self.typestore.serialize_cdr(self.typestore.types["sensor_msgs/msg/Image"](**bit),"sensor_msgs/msg/Image"))
            }
        }
        return cbor2.dumps(temp)

    def cbor2_loads(self,msg:bytes):
        return cbor2.loads(msg)

    def getTopic(self,name:str,type:str,typedef:str=None) -> RosTopic:
        self.register(type,typedef)
        return RosTopic(self,name,type,typedef)

    def deserialize(self,hex:str,types:str,typedefine:str=None) -> dict:
        temp=cbor2.loads(hex)
        temp["msg"]["bytes"]=self.buffer2obj(temp["msg"]["bytes"],types,typedefine)
        return temp

    def buffer2obj(self,buffer:str,types:str,typedefine:str=None):
        self.register(types,typedefine)
        return self.typestore.deserialize_cdr(buffer,types)
    
    def serialize(self,obj:dict,types:str=None,typedefine:str=None) -> bytes:
        obj["msg"]["bytes"]=self.obj2buffer(obj["msg"]["bytes"],types,typedefine)
        return cbor2.dumps(obj)
        

    def obj2buffer(self,obj,types:str=None,typedefine:str=None) -> bytes:
        if type(obj) == dict:
            if types:
                if types in self.typestore.types:
                    obj=self.typestore.types[types](**obj)
                else:
                    self.register(types,typedefine)
            else:
                raise Exception("obj的类型未定义")

        return bytes(self.typestore.serialize_cdr(obj,obj.__msgtype__))

    def register(self,types:str,definition:str=None):
        if not types in self.typestore.types:
            if definition:
                self.typestore.register(get_types_from_msg(definition,types))
            else:
                raise Exception(f"{types}的类型未定义")


if __name__ == "__main__":
    obj=RosmsgTools()
    b64="o2JvcGdwdWJsaXNoZXRvcGljZy9vcGVuYWljbXNno2RzZWNzGmhX/t9lbnNlY3MaKb+c8WVieXRlc1gnAAEAAB8AAADmjqXmlLbliLDor4bliKvlm77lg4/kv6Hlj7cxLzMA"
    define='''
        # This was originally provided as an example message.\n# It is deprecated as of Foxy\n# It is recommended to create your own semantically meaningful message.\n# However if you would like to continue using this please use the equivalent in example_msgs.\n\nstring data\n
        '''
    hex=base64.b64decode(b64)


    #print(hex)
    obj.register("user/msg/Mymsg",define)
    #print(obj.typestore.types)

    #print(obj.deserialize(base64.b64decode(b64_),"user/msg/Mymsg"))
    res_dict=obj.deserialize(hex,"user/msg/Mymsg")
    print(res_dict)
    bin=obj.serialize(res_dict)
    print(bin==hex)

    import json
    import numpy as np
    with open(r"D:\CodeProject\smartcar\cost\src\map.b64",'r') as f:
       hex=base64.b64decode(f.read())
    
    with open(r"D:\CodeProject\smartcar\cost\src\response.json",'r') as f:
        response_temp=json.load(f)["values"]

    with open(r"D:\CodeProject\smartcar\cost\src\imgmessage.txt",'r') as f:
        img_temp=base64.b64decode(f.read())

    #print(img_temp["msg"]["bytes"])

    
    for index,item in enumerate(response_temp['topics']):
        if item in ["/proxy/image"]:
            obj.register(response_temp['types'][index],response_temp['typedefs_full_text'][index])
            res_dict=obj.deserialize(img_temp,response_temp['types'][index])
    print(res_dict["msg"]["bytes"])
    bit={
        "header":{
            "stamp":{
                "sec":0,
                "nanosec":0
            },
            "frame_id":""
        },
        "height":48,
        "width":64,
        "encoding":"bgr8",
        "step":192,
        "data":res_dict["msg"]["bytes"].data,
    }

    print(obj.img_serialize(np.load("D:\CodeProject\smartcar\cost\src\map.npy")))
