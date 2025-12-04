# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class BdSubnetTask(BaseTask):
    """
    Tâche spécifique pour 'bd_subnet'.
    Gère fvSubnet et extrait le BD parent.
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            
            # DN: uni/tn-[tenant]/BD-[bd]/subnet-[ip]
            tenant = ""
            match_tn = re.search(r'/tn-([^/]+)/', dn)
            if match_tn: tenant = match_tn.group(1)
            
            bd = ""
            match_bd = re.search(r'/BD-([^/]+)/', dn)
            if match_bd: bd = match_bd.group(1)
            
            # IP and Mask
            ip_str = attr.get('ip', '')
            gateway = ip_str
            mask = ""
            if '/' in ip_str:
                parts = ip_str.split('/')
                gateway = parts[0]
                mask = parts[1]
            
            row_data = {
                'tenant': tenant,
                'bd': bd,
                'description': attr.get('descr'),
                'gateway': gateway,
                'mask': mask,
                'scope': attr.get('scope')
            }
            
            rows.append(row_data)
                
        return rows
