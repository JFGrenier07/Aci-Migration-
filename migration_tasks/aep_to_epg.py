# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class AepToEpgTask(BaseTask):
    """
    Tâche spécifique pour 'aep_to_epg'.
    Gère infraRsFuncToEpg.
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            tDn = attr.get('tDn', '')
            
            # Parent: AEP
            # dn: uni/infra/attentp-[aep_name]/rsfuncToEpg-[tDn]
            aep_name = ""
            match_aep = re.search(r'attentp-([^/]+)/', dn)
            if match_aep:
                aep_name = match_aep.group(1)
            
            # Target EPG
            # tDn: uni/tn-[tenant]/ap-[ap]/epg-[epg]
            tenant = ""
            ap = ""
            epg = ""
            
            match_tn = re.search(r'/tn-([^/]+)', tDn)
            if match_tn: tenant = match_tn.group(1)
            
            match_ap = re.search(r'/ap-([^/]+)', tDn)
            if match_ap: ap = match_ap.group(1)
            
            match_epg = re.search(r'/epg-([^/]+)', tDn)
            if match_epg: epg = match_epg.group(1)
            
            row_data = {
                'aep': aep_name,
                'tenant': tenant,
                'ap': ap,
                'epg': epg,
                'encap': attr.get('encap', ''),
                'primary_encap': attr.get('primaryEncap', ''),
                'mode': attr.get('mode', 'regular')
            }
            
            rows.append(row_data)
                
        return rows
