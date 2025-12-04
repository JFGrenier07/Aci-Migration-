# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class RouteControlContextTask(BaseTask):
    """
    Tâche spécifique pour 'route_control_context'.
    Gère rtctrlCtxP et extrait le profil parent et le L3Out.
    """
    
    def extract(self):
        super().extract()

    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            
            # DN: uni/tn-[tenant]/out-[l3out]/rtctrl-[profile]/ctx-[name]
            l3out = ""
            match_l3out = re.search(r'/out-([^/]+)/', dn)
            if match_l3out: l3out = match_l3out.group(1)
                
            profile = ""
            match_prof = re.search(r'/prof-([^/]+)/', dn)
            if match_prof: profile = match_prof.group(1)
            
            tenant = ""
            match_tn = re.search(r'/tn-([^/]+)/', dn)
            if match_tn: tenant = match_tn.group(1)
            
            # Match Rule via relation enfant rtctrlRsCtxPToSubjP
            match_rule = ""
            children = obj.get('children', [])
            for child in children:
                if 'rtctrlRsCtxPToSubjP' in child:
                    match_rule = child['rtctrlRsCtxPToSubjP']['attributes'].get('tnRtctrlSubjPName', '')

            row_data = {
                'route_control_context': attr.get('name'),
                'route_control_profile': profile,
                'l3out': l3out,
                'tenant': tenant,
                'action': attr.get('action'),
                'order': attr.get('order'),
                'description': attr.get('descr'),
                'match_rule': match_rule
            }
            
            rows.append(row_data)
                
        return rows
