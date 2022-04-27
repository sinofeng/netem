import os
import redis
import time
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED


REDIS_HOST = "192.168.1.196"
REDIS_PORT = 6379
REDIS_PASSWORD = "a123456"

SLOT_NUMS = 6666    # 仿真的时隙数量

class topo:
    def __init__(self) -> None:
        self.num_sw = 0     # 卫星交换机的个数
        self.link_delay = dict()    # 链路延迟 "1101-1102":13450, 0表示该链路断开
        self.node_ports = dict()    # 节点端口状态 "1101_to_1102":0, (0:down, 1:up)
        self.net_topo = dict()      # 节点拓扑信息 "1101":{1102,1110,1201,1601}
        self.redis = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=0,
                            password=REDIS_PASSWORD, decode_responses=True)

        self.read_topo()    # 读取拓扑信息


    def read_topo(self):
        links = self.redis.hgetall("all_links")
        for node in links:
            self.net_topo[node] = links[node].split(",")

        self.num_sw = len(self.net_topo)

        for sw1 in self.net_topo:
            for sw2 in self.net_topo[sw1]:
                if (sw1 < sw2):
                    self.node_ports[f"{sw2}-{sw1}"] = 0
                self.node_ports[f"{sw1}-{sw2}"] = 0
                self.link_delay[f"{sw1}-{sw2}"] = 0   # 链路为双向，只记录一次


    def update_link_delay(self):
        scripts = dict()

        for t in range(3):
            for sw in self.net_topo:
                scripts[sw] = ""

            delays = self.redis.hgetall(t)

            for link in self.link_delay:
                sw1, sw2 = link.split("-")
                d = delays.get(link)

                if d is None and self.link_delay[link] == 0:
                    # 当前时隙，链路断开，且上个时隙链路已经断开
                    continue
                elif d is None and self.link_delay[link] != 0:
                    # 当前时隙，链路断开，且上个时隙链路未断开
                    self.link_delay[link] = 0
                    # 给链路断开的两端发送消息
                    scripts[sw1] += f"ovs-vsctl del-port s{sw1}-s{sw2};"
                    scripts[sw2] += f"ovs-vsctl del-port s{sw2}-s{sw1};"
                    continue
                elif d is not None and self.link_delay[link] == 0:
                    # 当前时隙，链路恢复，且上个时隙链路已经断开
                    d = int(float(d) * 1000000)

                    self.link_delay[link] = d
                    # 给链路恢复的两端发送消息
                    scripts[sw1] += f"ovs-vsctl add-port s{sw1} s{sw1}-s{sw2} -- set Interface s{sw1}-s{sw2} ofport_request={sw2};"
                    scripts[sw2] += f"ovs-vsctl add-port s{sw2} s{sw2}-s{sw1} -- set Interface s{sw2}-s{sw1} ofport_request={sw1};"
                    scripts[sw1] += f"tc qdisc change dev s{sw1}-s{sw2} root netem delay {d};"
                    scripts[sw2] += f"tc qdisc change dev s{sw2}-s{sw1} root netem delay {d};"
                    continue
                elif d is not None and self.link_delay[link] != 0:
                    # 当前时隙，链路正常，且上个时隙链路未断开
                    d = int(float(d) * 1000000)

                    if d != self.link_delay[link]:  # 如果延迟发生变化
                        self.link_delay[link] = d
                        # 更新链路延迟
                        scripts[sw1] += f"tc qdisc change dev s{sw1}-s{sw2} root netem delay {d};"
                        scripts[sw2] += f"tc qdisc change dev s{sw2}-s{sw1} root netem delay {d};"
                    continue

            # for sw in scripts:
            #     if scripts[sw] == "":
            #         continue
            #     print(f"sudo docker exec -it s{sw} bash -c \"{scripts[sw]}\"")

            with ThreadPoolExecutor(max_workers=66) as pool:
                all_task = []
                for sw in scripts:
                    if scripts[sw] == "":
                        continue
                    all_task.append(pool.submit(os.system,
                      f"sudo docker exec -it s{sw} bash -c \"{scripts[sw]}\""))

            wait(all_task, return_when=ALL_COMPLETED)
            time.sleep(1)

