# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class IntSelToSwitchPolicyLeafTask(BaseTask):
    """
    Tâche spécifique pour 'int_sel_to_switch_policy_leaf'.
    Gère infraRsAccPortP (Relation Leaf Selector -> Interface Profile).
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            tDn = attr.get('tDn', '')
            
            # Parent: Leaf Selector (infraLeafS) -> Leaf Profile (infraNodeP)
            # dn: uni/infra/nprof-[leaf_profile]/leaves-[leaf_selector]-typ-range/rsaccPortP-[tDn]
            
            leaf_profile = ""
            leaf_selector = ""
            interface_profile = ""
            
            match_prof = re.search(r'nprof-([^/]+)/', dn)
            if match_prof: leaf_profile = match_prof.group(1)
            
            match_sel = re.search(r'leaves-([^/]+)-typ-', dn)
            if match_sel: leaf_selector = match_sel.group(1)
            
            # Interface Profile from tDn
            # tDn: uni/infra/accportprof-[name]
            match_int_prof = re.search(r'accportprof-([^/]+)', tDn)
            if match_int_prof:
                interface_profile = match_int_prof.group(1)
            else:
                interface_profile = tDn
            
            row_data = {
                'leaf_profile': leaf_profile,
                'leaf_selector': leaf_selector,
                'interface_profile': interface_profile
            }
            
            rows.append(row_data)
                
        return rows
