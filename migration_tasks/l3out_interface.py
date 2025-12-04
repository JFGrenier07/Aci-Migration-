# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class L3outInterfaceTask(BaseTask):
    """
    Tâche spécifique pour 'l3out_interface'.
    Gère l3extRsPathL3OutAtt et extrait les parents et le chemin.
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            tDn = attr.get('tDn', '') # topology/pod-[id]/paths-[node]/pathep-[eth]
            
            # DN: uni/tn-[tenant]/out-[l3out]/lnodep-[node_prof]/lifp-[int_prof]/rspathL3OutAtt-[tDn]
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
            
            # Extract Pod, Node, Path from tDn
            pod_id = ""
            node_id = ""
            path_ep = ""
            
            match_pod = re.search(r'pod-([0-9]+)', tDn)
            if match_pod: pod_id = match_pod.group(1)
            
            # paths-[node_id] or nodes-[node_id] ? Usually paths-
            match_node = re.search(r'paths-([0-9]+)', tDn)
            if match_node: node_id = match_node.group(1)
            
            match_path = re.search(r'pathep-\[(.+?)\]', tDn)
            if match_path:
                path_ep = match_path.group(1)
            else:
                # Fallback simple
                match_path_simple = re.search(r'pathep-([^/]+)', tDn)
                if match_path_simple: path_ep = match_path_simple.group(1)

            row_data = {
                'l3out': l3out,
                'node_profile': node_profile,
                'interface_profile': interface_profile,
                'tenant': tenant,
                'pod_id': pod_id,
                'node_id': node_id,
                'path_ep': path_ep,
                'interface_type': attr.get('ifInstT'),
                'encap': attr.get('encap'),
                'mode': attr.get('mode'),
                'mtu': attr.get('mtu'),
                'address': attr.get('addr'),
                'ipv6': '', # Pas d'attribut évident pour ipv6 sur cet objet
                'description': attr.get('descr')
            }
            
            rows.append(row_data)
                
        return rows
