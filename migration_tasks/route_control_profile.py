# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class RouteControlProfileTask(BaseTask):
    """
    Tâche spécifique pour 'route_control_profile'.
    Gère rtctrlProfile et extrait le L3Out parent.
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            
            # DN: uni/tn-[tenant]/out-[l3out]/rtctrl-[profile]
            l3out = ""
            match_l3out = re.search(r'/out-([^/]+)/', dn)
            if match_l3out:
                l3out = match_l3out.group(1)
                
            tenant = ""
            match_tn = re.search(r'/tn-([^/]+)/', dn)
            if match_tn:
                tenant = match_tn.group(1)

            row_data = {
                'route_control_profile': attr.get('name'),
                'description': attr.get('descr'),
                'l3out': l3out,
                'tenant': tenant
            }
            
            rows.append(row_data)
                
        return rows
