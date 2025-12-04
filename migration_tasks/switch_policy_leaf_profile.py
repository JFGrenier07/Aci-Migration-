# -*- coding: utf-8 -*-
from .base_task import BaseTask

class SwitchPolicyLeafProfileTask(BaseTask):
    """
    Tâche spécifique pour 'switch_policy_leaf_profile'.
    Gère infraNodeP et filtre les profils système.
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            name = attr.get('name', '')
            
            # Filtrer les profils système
            if name.startswith('system-'):
                continue
                
            # Utiliser la logique standard pour le reste
            row_data = {}
            for header in headers:
                aci_attr = self.attributes_map.get(header)
                if aci_attr:
                    val = attr.get(aci_attr)
                    if val == 'yes': val = 'true'
                    if val == 'no': val = 'false'
                    row_data[header] = val
                elif header == 'leaf_profile':
                    row_data[header] = name
                elif header in attr:
                    row_data[header] = attr[header]
            
            rows.append(row_data)
                
        return rows
