import os
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
from utils.topo import topo


# OVSLOG_DIR = "/root/logfile/"
# # SCRIPT_DIR = "/root/scripts/"
OVSLOG_DIR = "/home/s/tmp/logfile/"
SCRIPT_DIR = "/home/s/tmp/scripts/"


# 启动 OVS 容器
def run_ovs_docker(tp:topo):

    for sw_no in tp.net_topo:
        sw_no = str(sw_no)

        filename = SCRIPT_DIR + f"s{sw_no}_ovs_init.sh"
        _write_init_ovs_script(filename, sw_no)

        print(f"created ovs container: s{sw_no}")
        os.system(f"sudo docker create -it --name=s{sw_no} --privileged \
                -v /dev/hugepages:/dev/hugepages \
                -v {OVSLOG_DIR}:/root/logfile \
                -v {SCRIPT_DIR}:/root/script \
                ovsdpdk > /dev/null")
        os.system(f"sudo docker start s{sw_no} > /dev/null")
        os.system(f"sudo docker exec -it s{sw_no} sh /root/script/s{sw_no}_ovs_init.sh > /dev/null")


# 创建 veth peer，并挂载到对应的容器
def mount_veth_peer(tp:topo):
    print("mount veth peer")

    filename = SCRIPT_DIR + "mount_veth_peer.sh"
    with open(filename, 'w+') as file:
        for sw1 in tp.net_topo:
            for sw2 in tp.net_topo[sw1]:
                if sw1 < sw2:
                    continue
                p1_2 = f"s{sw1}-s{sw2}"
                p2_1 = f"s{sw2}-s{sw1}"

                # 先为每个 veth peer 用 add 添加 netem delay, 后续只用 change 命令
                file.write(f"""
sudo ip link add {p1_2} type veth peer name {p2_1} > /dev/null
sudo ip link set dev {p1_2} name {p1_2} netns $(sudo docker inspect -f '{{{{.State.Pid}}}}' s{sw1}) up
sudo ip link set dev {p2_1} name {p2_1} netns $(sudo docker inspect -f '{{{{.State.Pid}}}}' s{sw2}) up
docker exec -it s{sw1} tc qdisc add dev {p1_2} root netem delay 1
docker exec -it s{sw2} tc qdisc add dev {p2_1} root netem delay 1
""")

    # os.system(f"sudo sh {filename}")



def destroy(tp:topo):
    for sw in tp.net_topo:
        os.system(f"sudo docker stop s{sw}; sudo docker rm s{sw}")



def _write_init_ovs_script(filename:str, sw_no:str):

    coreid = (int(sw_no[:2]) - 11) * 11 + int(sw_no[2:])
    ip4 = f"192.168.{sw_no[:2]}.{int(sw_no[2:])}"
    with open(filename, 'w+') as file:
        file.write(f"""
# 创建数据库文件
mkdir -p /usr/local/etc/openvswitch
ovsdb-tool create /usr/local/etc/openvswitch/conf.db \\
    /usr/local/share/openvswitch/vswitch.ovsschema

# 启动数据库
mkdir -p /usr/local/var/run/openvswitch
mkdir -p /usr/local/var/log/openvswitch
ovsdb-server --remote=punix:/usr/local/var/run/openvswitch/db.sock \\
    --remote=db:Open_vSwitch,Open_vSwitch,manager_options \\
    --private-key=db:Open_vSwitch,SSL,private_key \\
    --certificate=db:Open_vSwitch,SSL,certificate \\
    --bootstrap-ca-cert=db:Open_vSwitch,SSL,ca_cert \\
    --pidfile --detach --log-file

# 初始化数据库
ovs-vsctl --no-wait init

# 配置使用DPDK, pmd-cpu-mask 要用16进制
ovs-vsctl --no-wait set Open_vSwitch . other_config:pmd-cpu-mask={hex(1<<coreid)}
ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-socket-mem="1024"
ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-init=true

# 启动 Open vSwitch 守护进程
ovs-vswitchd --pidfile --detach --log-file=/root/logfile/s{sw_no}-vswitchd.log

# 创建 bridge, 并为本地端口配置ip地址
ovs-vsctl add-br s{sw_no} -- set bridge s{sw_no} datapath_type=netdev
ifconfig s{sw_no} {ip4} netmask 255.255.0.0 up
route add default dev s{sw_no}

# 设置 openflow, 才可连接ONOS控制器, 只能用OpenFlow13
ovs-vsctl set bridge s{sw_no} protocols=OpenFlow13

# fail-mode 可设置为standalone, secure
# standalone: ovs会自动学习如何转发。
# secure: 无法连接控制器时, 只按本地流表转发, 若无法匹配则丢弃。
ovs-vsctl set-fail-mode s{sw_no} secure

# 本地流表设置
ovs-ofctl add-flow s{sw_no} "ip,nw_dst={ip4} action=output:LOCAL"
ovs-ofctl add-flow s{sw_no} "arp,nw_dst={ip4} action=output:LOCAL"
""")

