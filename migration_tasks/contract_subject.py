# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class ContractSubjectTask(BaseTask):
    """
    Tâche spécifique pour 'contract_subject'.
    Gère vzSubj et extrait le Contract parent.
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            
            # DN: uni/tn-[tenant]/brc-[contract]/subj-[subject]
            contract = ""
            match_brc = re.search(r'/brc-([^/]+)/', dn)
            if match_brc: contract = match_brc.group(1)
            
            tenant = ""
            match_tn = re.search(r'/tn-([^/]+)/', dn)
            if match_tn: tenant = match_tn.group(1)
            
            row_data = {
                'subject': attr.get('name'),
                'contract': contract,
                'tenant': tenant,
                'description': attr.get('descr'),
                'reverse_filter': attr.get('revFltPorts'), # yes/no
                'priority': attr.get('prio'),
                'target_dscp': attr.get('targetDscp'),
                'apply_both_direction': attr.get('consMatchT'), # A vérifier mapping
                'name_alias': attr.get('nameAlias')
            }
            
            rows.append(row_data)
                
        return rows
