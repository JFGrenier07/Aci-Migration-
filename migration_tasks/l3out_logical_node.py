# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class L3outLogicalNodeTask(BaseTask):
    """
    Tâche spécifique pour 'l3out_logical_node'.
    Gère l3extRsNodeL3OutAtt et extrait les parents et IDs.
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            tDn = attr.get('tDn', '') # topology/pod-[id]/node-[id]
            
            # DN: uni/tn-[tenant]/out-[l3out]/lnodep-[profile]/rsnodeL3OutAtt-[tDn]
            l3out = ""
            match_l3out = re.search(r'/out-([^/]+)/', dn)
            if match_l3out: l3out = match_l3out.group(1)
                
            node_profile = ""
            match_prof = re.search(r'/lnodep-([^/]+)/', dn)
            if match_prof: node_profile = match_prof.group(1)
            
            tenant = ""
            match_tn = re.search(r'/tn-([^/]+)/', dn)
            if match_tn: tenant = match_tn.group(1)
            
            # Extract Node ID and Pod ID from tDn
            node_id = ""
            pod_id = ""
            match_node = re.search(r'node-([0-9]+)', tDn)
            if match_node: node_id = match_node.group(1)
            
            match_pod = re.search(r'pod-([0-9]+)', tDn)
            if match_pod: pod_id = match_pod.group(1)

            row_data = {
                'node_id': node_id,
                'pod_id': pod_id,
                'l3out': l3out,
                'node_profile': node_profile,
                'tenant': tenant,
                'router_id': attr.get('rtrId'),
                'router_id_as_loopback': 'True' if attr.get('rtrIdLoopBack') == 'yes' else 'False',
                'description': attr.get('descr')
            }
            
            rows.append(row_data)
                
        return rows
