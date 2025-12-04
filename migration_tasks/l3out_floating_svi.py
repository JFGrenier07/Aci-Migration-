# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class L3outFloatingSviTask(BaseTask):
    """
    Tâche spécifique pour 'l3out_floating_svi'.
    Gère l3extVirtualLIfP et extrait les parents.
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            
            # DN: uni/tn-[tenant]/out-[l3out]/lnodep-[node_prof]/lifp-[int_prof]/vlifp-[name]
            l3out = ""
            match_l3out = re.search(r'/out-([^/]+)/', dn)
            if match_l3out: l3out = match_l3out.group(1)
                
            node_profile = ""
            match_node = re.search(r'/lnodep-([^/]+)/', dn)
            if match_node: node_profile = match_node.group(1)
            
            interface_profile = ""
            match_int = re.search(r'/lifp-([^/]+)/', dn)
            if match_int: interface_profile = match_int.group(1)
            
            tenant = ""
            match_tn = re.search(r'/tn-([^/]+)/', dn)
            if match_tn: tenant = match_tn.group(1)

            # Extract Pod, Node from nodeDn
            node_dn = attr.get('nodeDn', '')
            pod_id = ""
            node_id = ""
            match_pod = re.search(r'pod-([0-9]+)', node_dn)
            if match_pod: pod_id = match_pod.group(1)
            match_node = re.search(r'node-([0-9]+)', node_dn)
            if match_node: node_id = match_node.group(1)

            row_data = {
                'floating_svi': attr.get('name'),
                'l3out': l3out,
                'node_profile': node_profile,
                'interface_profile': interface_profile,
                'tenant': tenant,
                'encap': attr.get('encap'),
                'address': attr.get('addr'),
                'description': attr.get('descr'),
                'node_id': node_id,
                'pod_id': pod_id,
                'encap_scope': '' if attr.get('encapScope') == 'local' else attr.get('encapScope'),
                'mode': attr.get('mode'),
                'auto_state': attr.get('autostate'),
                'dscp': attr.get('targetDscp'),
                'ipv6_dad': attr.get('ipv6Dad'),
                'mtu': attr.get('mtu')
            }
            
            rows.append(row_data)
                
        return rows
