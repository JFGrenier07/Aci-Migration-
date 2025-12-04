# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class L3outExtsubnetTask(BaseTask):
    """
    Tâche spécifique pour 'l3out_extsubnet'.
    Gère l3extSubnet et extrait les parents.
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            
            # DN: uni/tn-[tenant]/out-[l3out]/instP-[extepg]/extsubnet-[network]
            l3out = ""
            match_l3out = re.search(r'/out-([^/]+)/', dn)
            if match_l3out: l3out = match_l3out.group(1)
                
            extepg = ""
            match_epg = re.search(r'/instP-([^/]+)/', dn)
            if match_epg: extepg = match_epg.group(1)
            
            tenant = ""
            match_tn = re.search(r'/tn-([^/]+)/', dn)
            if match_tn: tenant = match_tn.group(1)
            
            row_data = {
                'tenant': tenant,
                'l3out': l3out,
                'extepg': extepg,
                'network': attr.get('ip'),
                'subnet_name': attr.get('name'),
                'description': attr.get('descr'),
                'scope': attr.get('scope')
            }
            
            rows.append(row_data)
                
        return rows
