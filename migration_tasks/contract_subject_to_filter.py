# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class ContractSubjectToFilterTask(BaseTask):
    """
    Tâche spécifique pour 'contract_subject_to_filter'.
    Gère vzRsSubjFiltAtt et extrait les parents.
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            
            # DN: uni/tn-[tenant]/brc-[contract]/subj-[subject]/rssubjFiltAtt-[filter]
            tenant = ""
            match_tn = re.search(r'/tn-([^/]+)/', dn)
            if match_tn: tenant = match_tn.group(1)
            
            contract = ""
            match_brc = re.search(r'/brc-([^/]+)/', dn)
            if match_brc: contract = match_brc.group(1)
            
            subject = ""
            match_subj = re.search(r'/subj-([^/]+)/', dn)
            if match_subj: subject = match_subj.group(1)
            
            filter_name = attr.get('tnVzFilterName')
            
            # Direction is usually on the Subject, but here we are at Filter level.
            # Ansible module 'aci_contract_subject_to_filter' doesn't seem to have 'direction'.
            # Wait, the CSV header has 'direction'.
            # If it's not in the object, maybe it's 'both' by default or inherited.
            # Let's check if 'action' is present. Yes.
            
            # Handle potential trailing space in 'directives' column
            directives_col = 'directives'
            if 'directives ' in headers:
                directives_col = 'directives '
            
            row_data = {
                'tenant': tenant,
                'contract': contract,
                'subject': subject,
                'filter': filter_name,
                'action': attr.get('action'),
                'priority_override': attr.get('priorityOverride'),
                directives_col: attr.get('directives') if attr.get('directives') else 'none',
                'direction': 'both' # Default assumption, as it's not on this object
            }
            
            rows.append(row_data)
                
        return rows
