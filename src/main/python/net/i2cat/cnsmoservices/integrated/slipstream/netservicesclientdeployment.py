#!/usr/bin/env python

###
# This script deploys CNSMo network services in a SlipStream deployment.
# It is meant to be run by SlipStream, using a privileged user
#
# All ss-get/ss-set applies to local node variables, unless a node instance_id is prefixed.
#
# Requires the following parameters in slipstream application component:
# Input parameters:
# cnsmo.server.nodeinstanceid: Indicates the node.id of the component acting as CNSMO server
# vpn.server.nodeinstanceid: Indicates the node.id of the component acting as VPN server
# net.services.enable: A json encoded list of strings indicating the network services to be enabled. e.g. ['vpn', 'fw', 'lb']
#
# Output parameters:
# net.services.enabled: A json encoded list of strings indicating the network services that has been enabled. e.g. ['vpn', 'fw', 'lb']
###

import json
import os
import subprocess
import sys
import threading

path = os.path.dirname(os.path.abspath(__file__))
src_dir = path + "/../../../../../../../../../"
if src_dir not in sys.path:
    sys.path.append(src_dir)

from src.main.python.net.i2cat.cnsmoservices.vpn.run.slipstream.vpnclientdeployment import deployvpn
from src.main.python.net.i2cat.cnsmoservices.fw.run.slipstream.fwdeployment import deployfw

call = lambda command: subprocess.check_output(command, shell=True)


def main():
    netservices = get_net_services_to_enable()
    netservices_enabled = list()
    cnsmo_server_instance_id = call('ss-get --timeout=1200 cnsmo.server.nodeinstanceid').rstrip('\n')
    if not cnsmo_server_instance_id:
        # timeout! Abort the script immediately (ss-get will abort the whole deployment in short time)
        return -1

    if 'vpn' in netservices:
        vpn_server_instance_id = call('ss-get --timeout=1200 vpn.server.nodeinstanceid').rstrip('\n')
        if not vpn_server_instance_id:
            # timeout! Abort the script immediately (ss-get will abort the whole deployment in short time)
            return -1
        if deploy_vpn_and_wait(vpn_server_instance_id):
            netservices_enabled.append('vpn')
        else:
            return -1

    if 'fw' in netservices:
        if deploy_fw_and_wait(cnsmo_server_instance_id):
            netservices_enabled.append('fw')
        else:
            return -1

    if 'lb' in netservices:
        # nothing to do, lb is only in the server
        netservices_enabled.append('lb')

    call('ss-set net.services.enabled %s' % netservices_enabled)
    return 0


def deploy_vpn_and_wait(vpn_server_instance_id):
    tvpn = threading.Thread(target=deployvpn)
    tvpn.start()
    response = call('ss-get --timeout=1800 %s:net.i2cat.cnsmo.service.vpn.ready' % vpn_server_instance_id).rstrip('\n')
    if response != 'true':
        call('ss-abort \"Timeout waiting for VPN service to be established\"')
        return -1
    return 0


def deploy_fw_and_wait(cnsmo_server_instance_id):
    tfw = threading.Thread(target=deployfw, args=cnsmo_server_instance_id)
    tfw.start()
    response = call('ss-get --timeout=1800 net.i2cat.cnsmo.service.fw.ready').rstrip('\n')
    if response != 'true':
        call('ss-abort \"Timeout waiting for FW service to be established\"')
        return -1
    return 0


def get_net_services_to_enable():
    """
    :return: A list of strings representing which services must be enabled. e.g. ['vpn', 'fw', 'lb']
    """
    netservices_str = call('ss-get net.services.enable').rstrip('\n')
    netservices = json.loads(netservices_str)
    return netservices

main()

if __name__ == "__main__":
    main()
