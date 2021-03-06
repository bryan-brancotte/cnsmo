#!/usr/bin/env python

###
# This script is meant to be run by SlipStream, using a privileged user
#
# All ss-get/ss-set applies to local node variables, unless a node instance_id is prefixed.
###

import os
import subprocess
import sys
import threading
import time

path = os.path.dirname(os.path.abspath(__file__))
src_dir = path + "/../../../../../../../../../"
if src_dir not in sys.path:
    sys.path.append(src_dir)

from src.main.python.net.i2cat.cnsmoservices.vpn.manager.vpn import VPNManager

call = lambda command: subprocess.check_output(command, shell=True)


def main():
    deploycnsmo()
    deployvpn()


def deploycnsmo():
    ss_nodename = call('ss-get nodename').rstrip('\n')
    ss_node_instance = call('ss-get id').rstrip('\n')
    instance_id = "%s.%s" % (ss_nodename, ss_node_instance)
    log_file = os.getcwd() + "/cnsmo/vpn.log"

    hostname = call('ss-get hostname').rstrip('\n')
    dss_port = "6379"
    redis_address = "%s:%s" % (hostname, dss_port)

    date = call('date')
    logToFile("Launching CNSMO at %s" % date, log_file, "w+")


    # Launch REDIS
    tr = threading.Thread(target=launchRedis, args=(hostname, dss_port))
    tr.start()
    # TODO implement proper way to detect when the redis server is ready
    time.sleep(1)

    # Launch CNSMO
    call('ss-display \"Launching CNSMO...\"')
    tss = threading.Thread(target=launchSystemState, args=(hostname, dss_port))
    tss.start()
    # TODO implement proper way to detect when the system state is ready
    time.sleep(1)
    call("ss-set net.i2cat.cnsmo.dss.address %s" % redis_address)
    call('ss-set net.i2cat.cnsmo.core.ready true')
    call('ss-display \"CNSMO is ready!\"')


def deployvpn():
    ss_nodename = call('ss-get nodename').rstrip('\n')
    ss_node_instance = call('ss-get id').rstrip('\n')
    instance_id = "%s.%s" % (ss_nodename, ss_node_instance)
    hostname = call('ss-get hostname').rstrip('\n')
    log_file = os.getcwd() + "/cnsmo/vpn.log"
    ifaces_prev = getCurrentInterfaces()

    call('ss-set vpn.server.nodeinstanceid %s' % instance_id)

    # wait for CNSMO core
    call('ss-get net.i2cat.cnsmo.core.ready')
    redis_address = call("ss-get net.i2cat.cnsmo.dss.address").rstrip('\n')

    date = call('date')
    logToFile("Deploying VPN at %s" % date, log_file, "a")

    call('ss-display \"Deploying VPN components...\"')

    # Launch VPN orchestrator
    call('ss-display \"VPN: Launching VPN orchestrator...\"')
    vpn_orchestrator = VPNManager(redis_address)
    to = threading.Thread(target=vpn_orchestrator.start)
    to.start()
    # TODO implement proper way to detect when the orchestrator is ready (using systemstate?)
    time.sleep(1)
    call('ss-set net.i2cat.cnsmo.service.vpn.orchestrator.ready true')

    # Wait for orchestrator
    call('ss-get net.i2cat.cnsmo.service.vpn.orchestrator.ready')
    # Launch the rest of VPN services

    # Launch VPN configurator
    tc = threading.Thread(target=launchVPNConfigurator, args=(hostname, redis_address, instance_id))
    tc.start()
    # TODO implement proper way to detect when the configurator is ready (using systemstate?)
    time.sleep(1)
    call('ss-set net.i2cat.cnsmo.service.vpn.configurator.listening true')

    # Launch VPN server
    ts = threading.Thread(target=launchVPNServer, args=(hostname, redis_address, instance_id))
    ts.start()
    # TODO implement proper way to detect when the server is ready (using systemstate?)
    time.sleep(1)
    call('ss-set net.i2cat.cnsmo.service.vpn.server.listening true')

    # Wait for configurator and server to be ready
    call('ss-get net.i2cat.cnsmo.service.vpn.configurator.listening')
    call('ss-get net.i2cat.cnsmo.service.vpn.server.listening')

    # Wait for clients
    call('ss-display \"VPN: Looking for all clients...\"')
    # All instances in the deployment except the slipstream orchestrator and the one running the vpn server are considered vpn clients
    all_instances = ss_getinstances()
    # remove slipstream orchestrator instances
    client_instances = [x for x in all_instances if not x.startswith("orchestrator")]
    # remove this instance
    client_instances.remove(instance_id)

    call('ss-display \"VPN: Waiting for all clients...\"')
    # wait for clients to be ready: instance_id:net.i2cat.cnsmo.service.vpn.client.waiting=true
    for client_id in client_instances:
        call("ss-get --timeout=1800 %s:net.i2cat.cnsmo.service.vpn.client.listening" % client_id)

    # Deploy VPN
    call('ss-display \"VPN: Deploying VPN...\"')
    vpn_orchestrator.deploy_blocking()

    time.sleep(5)

    date = call('date')
    logToFile("VPN deployed at %s" % date, log_file, "a")

    # assuming the VPN interface (probably tap0) is the only one created during this script execution
    vpn_iface = detect_new_interface_in_30_sec(ifaces_prev)
    if not vpn_iface:
        call("ss-abort \"%s:Timeout! Failed to locate tap interface, created by the VPN\"" % instance_id)
        return -1

    vpn_local_ipv4_address = getInterfaceIPv4Address(vpn_iface)
    vpn_local_ipv6_address = getInterfaceIPv6Address(vpn_iface)
    logToFile("VPN using interface %s with ipaddr %s and ipv6addr %s" %
              (vpn_iface, vpn_local_ipv4_address, vpn_local_ipv6_address), log_file, "a")

    call("ss-set vpn.address %s" % vpn_local_ipv4_address)
    call("ss-set vpn.address6 %s" % vpn_local_ipv6_address)

    # Communicate that the VPN has been established
    call('ss-set net.i2cat.cnsmo.service.vpn.ready true')

    call("ss-display \"VPN: VPN has been established! Using interface %s with ipaddr %s and ipv6addr %s\"" %
         (vpn_iface, vpn_local_ipv4_address, vpn_local_ipv6_address))

    print "VPN deployed!"


def detect_new_interface_in_30_sec(ifaces_prev):
    vpn_iface = do_detect_new_interface(ifaces_prev)
    attempts = 0
    while not vpn_iface and attempts < 6:
        time.sleep(5)
        vpn_iface = do_detect_new_interface(ifaces_prev)
        attempts += 1
    return vpn_iface


def do_detect_new_interface(ifaces_prev):
    vpn_iface = None
    for current_iface in getCurrentInterfaces():
        if current_iface not in ifaces_prev:
            vpn_iface = current_iface
    return vpn_iface


def launchRedis(hostname, dss_port):
    call('ss-display \"Launching REDIS...\"')
    call('redis-server')


def launchSystemState(hostname, dss_port):
    call('ss-display \"Launching CNSMO...\"')
    call("python cnsmo/cnsmo/src/main/python/net/i2cat/cnsmo/run/systemstate.py -a %s -p %s" % (hostname, dss_port))


def launchVPNConfigurator(hostname, redis_address, instance_id):
    call('ss-display \"VPN: Launching VPN configurator...\"')
    call("python cnsmo/cnsmo/src/main/python/net/i2cat/cnsmoservices/vpn/run/configurator.py -a %s -p 9093 -r %s -s VPNConfigurator-%s --vpn-server-ip %s --vpn-server-port 1194 --vpn-address 10.10.10.0 --vpn-mask 255.255.255.0" % (hostname, redis_address, instance_id, hostname))


def launchVPNServer(hostname, redis_address, instance_id):
    call('ss-display \"VPN: Launching VPN server...\"')
    call("python cnsmo/cnsmo/src/main/python/net/i2cat/cnsmoservices/vpn/run/server.py -a %s -p 9092 -r %s -s VPNServer-%s" % (hostname, redis_address, instance_id))


def getCurrentInterfaces():
    return call("""ls /sys/class/net | sed -e s/^\(.*\)$/\1/ | paste -sd ','""").rstrip('\n').split(',')


def getInterfaceIPv4Address(iface):
    return call("ifconfig " + iface + " | grep 'inet addr:' | cut -d: -f2 | awk '{ print $1}'").rstrip('\n')


def getInterfaceIPv6Address(iface):
    return call("ifconfig " + iface + "| awk '/inet6 / { print $3 }'").rstrip('\n')


def logToFile(message, filename, filemode):
    f = None
    try:
        f = open(filename, filemode)
        f.write(message)
    finally:
        if f:
            f.close()


# Gets the instances that compose the deployment
# NOTE: Currently there is no way to directly retrieve all nodes intances in a deployment.
#       As of now we have to find them out by parsing the ss:groups, and then the node's
#       <nodename>:<id> runtime parameters.
#       There is an issue to implement this enhancement: https://github.com/slipstream/SlipStreamServer/issues/628
def ss_getinstances():
    # ss:groups  cyclone-fr2:VPN,cyclone-fr1:client2,cyclone-fr2:client1

    groups = call("ss-get ss:groups").rstrip('\n')
    cloud_node_pairs = groups.split(",")

    nodes = list()
    for pair in cloud_node_pairs:
        nodes.append(pair.split(":")[1])

    # nodes = VPN, client2, client1

    indexes = dict()
    # client1:ids     1,2
    for node in nodes:
        indexes[node] = call("ss-get %s:ids" % node).split(",")

    # {"client1":["1","2"]}
    instances = list()
    for node, node_indexes in indexes.iteritems():
        for index in node_indexes:
            instances.append(node + "." + index.rstrip('\n'))

    return instances

main()
