# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class InterfaceConfigTask(BaseTask):
    """
    Tâche spécifique pour 'interface_config'.
    Gère infraPortConfig (et fabricPortConfig si besoin).
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            
            # Reconstruire l'interface: card/port/sub
            card = attr.get('card', '1')
            port = attr.get('port', '1')
            sub = attr.get('subPort', '0')
            
            interface = f"{card}/{port}"
            if sub != '0':
                interface += f"/{sub}"
                
            # Policy Group depuis assocGrp
            # DN: uni/infra/funcprof/accportgrp-[name]
            policy_group = ""
            assoc_grp = attr.get('assocGrp', '')
            if assoc_grp:
                # Extraire le nom à la fin du DN
                match_pg = re.search(r'([^/]+)$', assoc_grp)
                if match_pg:
                    # Enlever le préfixe si présent (ex: accportgrp-NAME)
                    pg_full = match_pg.group(1)
                    if '-' in pg_full:
                        policy_group = pg_full.split('-', 1)[1]
                    else:
                        policy_group = pg_full

            # Admin State
            shutdown = attr.get('shutdown', 'no')
            admin_state = 'down' if shutdown == 'yes' else 'up'
            
            row_data = {
                'interface': interface,
                'node': attr.get('node'),
                'policy_group': policy_group,
                'description': attr.get('descr'),
                'role': attr.get('role', 'leaf'), # Default leaf
                'port_type': 'access', # infraPortConfig = access
                'admin_state': admin_state,
                'breakout': attr.get('brkoutMap'),
                'pc_member': attr.get('pcMember')
            }
            
            rows.append(row_data)
                
        return rows
