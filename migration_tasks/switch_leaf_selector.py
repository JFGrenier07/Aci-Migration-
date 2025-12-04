# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class SwitchLeafSelectorTask(BaseTask):
    """
    Tâche spécifique pour 'switch_leaf_selector'.
    Gère infraLeafS et ses enfants (infraNodeBlk).
    """
    
    def extract(self):
        # On a besoin des enfants pour les blocs de noeuds
        super().extract()

    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            
            # Parent: Leaf Profile
            # dn: uni/infra/nprof-[profile]/leaves-[selector]-typ-range
            leaf_profile = ""
            match_prof = re.search(r'nprof-([^/]+)/', dn)
            if match_prof:
                leaf_profile = match_prof.group(1)
            
            # Filtrer les profils système
            if leaf_profile.startswith('system-'):
                continue
            
            # Enfants: Node Blocks
            children = obj.get('children', [])
            node_blocks = []
            
            for child in children:
                if 'infraNodeBlk' in child:
                    blk_attr = child['infraNodeBlk']['attributes']
                    node_blocks.append(blk_attr)
            
            # Si aucun bloc, on crée une ligne générique
            if not node_blocks:
                row_data = {
                    'leaf_profile': leaf_profile,
                    'leaf': attr.get('name'),
                    'leaf_node_blk': '',
                    'from': '',
                    'to': '',
                    'description': attr.get('descr')
                }
                rows.append(row_data)
            else:
                # Une ligne par bloc
                for blk in node_blocks:
                    row_data = {
                        'leaf_profile': leaf_profile,
                        'leaf': attr.get('name'),
                        'leaf_node_blk': blk.get('name'),
                        'from': blk.get('from_'),
                        'to': blk.get('to_'),
                        'description': attr.get('descr')
                    }
                    rows.append(row_data)
                
        return rows
