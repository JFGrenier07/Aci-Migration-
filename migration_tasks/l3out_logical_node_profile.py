# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class L3outLogicalNodeProfileTask(BaseTask):
    """
    Tâche spécifique pour 'l3out_logical_node_profile'.
    Gère l3extLNodeP et extrait le L3Out parent.
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            
            # DN: uni/tn-[tenant]/out-[l3out]/lnodep-[name]
            l3out = ""
            match_l3out = re.search(r'/out-([^/]+)/', dn)
            if match_l3out: l3out = match_l3out.group(1)
                
            tenant = ""
            match_tn = re.search(r'/tn-([^/]+)/', dn)
            if match_tn: tenant = match_tn.group(1)

            row_data = {
                'node_profile': attr.get('name'),
                'l3out': l3out,
                'tenant': tenant,
                'description': attr.get('descr'),
                'tag': attr.get('tag')
            }
            
            rows.append(row_data)
                
        return rows
