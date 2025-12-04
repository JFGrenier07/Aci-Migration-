# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class L3outBgpPeerTask(BaseTask):
    """
    Tâche spécifique pour 'l3out_bgp_peer'.
    Gère bgpPeerP (et bgpInfraPeerP) et extrait les parents et ASNs.
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            
            # DN: uni/tn-[tenant]/out-[l3out]/lnodep-[node_prof]/lifp-[int_prof]/rspathL3OutAtt-[path]/peerP-[ip]
            # OU: uni/tn-[tenant]/out-[l3out]/lnodep-[node_prof]/peerP-[ip]
            
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
            
            # Path EP extraction is complex from DN here because it's encoded in rspathL3OutAtt-[...]
            # We might need to parse it carefully or leave it empty if not critical
            path_ep = ""
            match_path = re.search(r'/rspathL3OutAtt-\[(.+?)\]/', dn)
            if match_path:
                # topology/pod-1/paths-101/pathep-[eth1/1]
                full_path = match_path.group(1)
                match_leaf_port = re.search(r'pathep-\[(.+?)\]', full_path)
                if match_leaf_port:
                    path_ep = match_leaf_port.group(1)
                else:
                     # Fallback simple
                    match_path_simple = re.search(r'pathep-([^/]+)', full_path)
                    if match_path_simple: path_ep = match_path_simple.group(1)

            # Pod/Node ID from path
            pod_id = ""
            node_id = ""
            if match_path:
                full_path = match_path.group(1)
                match_pod = re.search(r'pod-([0-9]+)', full_path)
                if match_pod: pod_id = match_pod.group(1)
                match_node_id = re.search(r'paths-([0-9]+)', full_path)
                if match_node_id: node_id = match_node_id.group(1)

            # Remote ASN from child bgpAsP
            remote_asn = ""
            children = obj.get('children', [])
            for child in children:
                if 'bgpAsP' in child:
                    remote_asn = child['bgpAsP']['attributes'].get('asn', '')
            
            # Local ASN from child bgpLocalAsnP
            local_as_number = ""
            local_as_number_config = ""
            for child in children:
                if 'bgpLocalAsnP' in child:
                    local_as_number = child['bgpLocalAsnP']['attributes'].get('localAsn', '')
                    local_as_number_config = child['bgpLocalAsnP']['attributes'].get('asnPropagate', '')

            row_data = {
                'peer_ip': attr.get('addr'),
                'l3out': l3out,
                'node_profile': node_profile,
                'interface_profile': interface_profile,
                'tenant': tenant,
                'pod_id': pod_id,
                'node_id': node_id,
                'path_ep': path_ep,
                'remote_asn': remote_asn,
                'local_as_number': local_as_number,
                'local_as_number_config': local_as_number_config,
                'description': attr.get('descr'),
                'admin_state': 'disabled' if attr.get('adminSt') == 'disabled' else 'enabled',
                'ttl': attr.get('ttl'),
                'weight': attr.get('weight'),
                'bgp_controls': attr.get('ctrl'), # List conversion needed?
                'peer_controls': attr.get('peerCtrl'),
                'address_type_controls': attr.get('addrTCtrl'),
            }
            
            rows.append(row_data)
                
        return rows
