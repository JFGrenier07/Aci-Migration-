# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class MatchRouteDestinationTask(BaseTask):
    """
    Tâche spécifique pour 'match_route_destination'.
    Gère rtctrlMatchRtDest et extrait la règle parente (match_rule).
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            
            # DN: uni/tn-[tenant]/out-[l3out]/subj-[subject]/dest-[dest]
            match_rule = ""
            match_subj = re.search(r'/subj-([^/]+)/', dn)
            if match_subj:
                match_rule = match_subj.group(1)
                
            tenant = ""
            match_tn = re.search(r'/tn-([^/]+)/', dn)
            if match_tn: tenant = match_tn.group(1)

            row_data = {
                'match_route_destination': attr.get('name'),
                'match_rule': match_rule,
                'tenant': tenant,
                'ip': attr.get('ip'),
                'aggregate': attr.get('aggregate'),
                'description': attr.get('descr')
            }
            
            rows.append(row_data)
                
        return rows
