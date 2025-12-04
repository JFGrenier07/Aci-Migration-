# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class EpgTask(BaseTask):
    """
    Tâche spécifique pour 'epg'.
    Gère fvAEPg et extrait le BD (fvRsBd) et l'AP (DN).
    """
    
    def extract(self):
        super().extract()

    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            
            # Extraction AP depuis DN
            # DN: uni/tn-[tenant]/ap-[ap]/epg-[epg]
            ap = ""
            match_ap = re.search(r'/ap-([^/]+)/', dn)
            if match_ap: ap = match_ap.group(1)
            
            tenant = ""
            match_tn = re.search(r'/tn-([^/]+)/', dn)
            if match_tn: tenant = match_tn.group(1)
            
            # Extraction BD depuis enfant fvRsBd
            bd = ""
            children = obj.get('children', [])
            for child in children:
                if 'fvRsBd' in child:
                    bd = child['fvRsBd']['attributes'].get('tnFvBDName', '')
            
            row_data = {
                'epg': attr.get('name'),
                'ap': ap,
                'tenant': tenant,
                'bd': bd,
                'description': attr.get('descr'),
                'priority': attr.get('prio'),
                'intra_epg_isolation': attr.get('pcEnfPref'), # enforced/unenforced ? A mapper
                'preferred_group': attr.get('prefGrMemb'), # include/exclude
                'flood_on_encap': attr.get('floodOnEncap'),
                'fwd_control': attr.get('fwdCtrl'),
                'match': attr.get('matchT'),
                'name_alias': attr.get('nameAlias')
            }
            
            rows.append(row_data)
                
        return rows
