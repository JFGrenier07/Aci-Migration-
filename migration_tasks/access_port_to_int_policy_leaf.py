# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class AccessPortToIntPolicyLeafTask(BaseTask):
    """
    Tâche spécifique pour 'access_port_to_int_policy_leaf'.
    Gère infraHPortS et ses enfants (infraPortBlk, infraRsAccBaseGrp).
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            
            # DN: uni/infra/accportprof-[profile]/hports-[selector]-typ-range
            interface_profile = ""
            match_prof = re.search(r'accportprof-([^/]+)/', dn)
            if match_prof: interface_profile = match_prof.group(1)
            
            # Filtrer les profils système
            if interface_profile.startswith('system-'):
                continue
                
            # Children
            children = obj.get('children', [])
            
            # Policy Group
            policy_group = ""
            for child in children:
                if 'infraRsAccBaseGrp' in child:
                    pg_dn = child['infraRsAccBaseGrp']['attributes'].get('tDn', '')
                    # Extraire le nom du PG si possible, ou garder le DN
                    # Le CSV original semble avoir le nom court: Access_Port_Policy_Group_L2_Global
                    # DN: uni/infra/funcprof/accportgrp-[name]
                    match_pg = re.search(r'accportgrp-([^/]+)', pg_dn)
                    if match_pg:
                        policy_group = match_pg.group(1)
                    else:
                        # Fallback bundle or other types
                        match_bundle = re.search(r'accbundle-([^/]+)', pg_dn)
                        if match_bundle:
                            policy_group = match_bundle.group(1)
                        else:
                            policy_group = pg_dn # Fallback full DN
            
            # Port Blocks
            port_blocks = []
            for child in children:
                if 'infraPortBlk' in child:
                    port_blocks.append(child['infraPortBlk']['attributes'])
            
            if not port_blocks:
                # Cas sans bloc (rare mais possible)
                row_data = {
                    'interface_profile': interface_profile,
                    'access_port_selector': attr.get('name'),
                    'description': attr.get('descr'),
                    'policy_group': policy_group,
                    'port_blk': '',
                    'from_port': '',
                    'to_port': ''
                }
                rows.append(row_data)
            else:
                for blk in port_blocks:
                    row_data = {
                        'interface_profile': interface_profile,
                        'access_port_selector': attr.get('name'),
                        'description': attr.get('descr'),
                        'policy_group': policy_group,
                        'port_blk': blk.get('name'),
                        'from_port': blk.get('fromPort'),
                        'to_port': blk.get('toPort')
                    }
                    rows.append(row_data)
                
        return rows
