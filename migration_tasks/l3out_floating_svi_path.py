# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class L3outFloatingSviPathTask(BaseTask):
    """
    Tâche spécifique pour 'l3out_floating_svi_path'.
    Gère l3extRsDynPathAtt et extrait les parents et le chemin.
    """
    
    def extract(self):
        # On cherche le parent l3extVirtualLIfP pour avoir accès à nodeDn et encap
        self.aci_class = 'l3extVirtualLIfP'
        super().extract()

    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            # Parent attributes (l3extVirtualLIfP)
            p_attr = obj.get('attributes', {})
            dn = p_attr.get('dn', '')
            
            # Extract basic info from DN
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
            
            floating_svi = ""
            match_svi = re.search(r'/vlifp-([^/]+)/', dn)
            if match_svi: floating_svi = match_svi.group(1)
            
            # Parent specific attributes
            node_dn = p_attr.get('nodeDn', '') # topology/pod-1/node-102
            encap = p_attr.get('encap', '')
            
            pod_id = ""
            node_id = ""
            match_pod = re.search(r'pod-([0-9]+)', node_dn)
            if match_pod: pod_id = match_pod.group(1)
            match_node_id = re.search(r'node-([0-9]+)', node_dn)
            if match_node_id: node_id = match_node_id.group(1)

            # Iterate children to find l3extRsDynPathAtt
            children = obj.get('children', [])
            for child in children:
                if 'l3extRsDynPathAtt' in child:
                    c_attr = child['l3extRsDynPathAtt']['attributes']
                    
                    # Child attributes
                    floating_ip = c_attr.get('floatingAddr')
                    tDn = c_attr.get('tDn', '') # uni/phys-Test_PHYSDOM_Floating
                    
                    domain = ""
                    domain_type = ""
                    
                    if '/phys-' in tDn:
                        domain_type = 'physical' # Ansible uses 'physical' not 'phys'
                        match = re.search(r'/phys-([^/]+)', tDn)
                        if match: domain = match.group(1)
                    elif '/l3dom-' in tDn:
                        domain_type = 'l3dom'
                        match = re.search(r'/l3dom-([^/]+)', tDn)
                        if match: domain = match.group(1)
                    elif '/vmmp-' in tDn:
                        domain_type = 'vmm' # Or vmware?
                        match = re.search(r'/dom-([^/]+)', tDn)
                        if match: domain = match.group(1)

                    row_data = {
                        'floating_svi': floating_svi,
                        'l3out': l3out,
                        'node_profile': node_profile,
                        'interface_profile': interface_profile,
                        'tenant': tenant,
                        'pod_id': pod_id,
                        'node_id': node_id,
                        'floating_ip': floating_ip, 
                        'encap': encap,
                        'mode': p_attr.get('mode'),
                        'for_primary': c_attr.get('forgedTransmit'), # Mapping check?
                        'domain': domain,
                        'domain_type': domain_type
                    }
                    
                    if row_data not in rows:
                        rows.append(row_data)
                
        return rows
