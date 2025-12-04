# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class L3outLogicalInterfaceProfileTask(BaseTask):
    """
    Tâche spécifique pour 'l3out_logical_interface_profile'.
    Gère l3extLIfP et extrait les parents.
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            
            # DN: uni/tn-[tenant]/out-[l3out]/lnodep-[profile]/lifp-[name]
            l3out = ""
            match_l3out = re.search(r'/out-([^/]+)/', dn)
            if match_l3out: l3out = match_l3out.group(1)
                
            node_profile = ""
            match_prof = re.search(r'/lnodep-([^/]+)/', dn)
            if match_prof: node_profile = match_prof.group(1)
            
            tenant = ""
            match_tn = re.search(r'/tn-([^/]+)/', dn)
            if match_tn: tenant = match_tn.group(1)

            row_data = {
                'interface_profile': attr.get('name'),
                'l3out': l3out,
                'node_profile': node_profile,
                'tenant': tenant,
                'description': attr.get('descr')
            }
            
            rows.append(row_data)
                
        return rows
