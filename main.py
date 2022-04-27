import os
import time
from utils.topo import topo
from utils.scripts import *

if __name__ == "__main__":
    os.system("sudo pwd")

    # 1. 创建拓扑
    tp = topo()

    # 2. 创建容器并启动 OVS
    run_ovs_docker(tp)

    # 3. 创建 veth peer，并挂载到对应的容器
    mount_veth_peer(tp)

    # 4. 开始维护链路（通断与延迟）
    tp.update_link_delay()

