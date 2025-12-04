# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class VlanPoolEncapBlockTask(BaseTask):
    """
    Tâche spécifique pour 'vlan_pool_encap_block'.
    Gère fvnsEncapBlk et extrait le pool parent.
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            
            # DN format: uni/infra/vlanns-[pool_name]-[mode]/from-[start]-to-[end]
            pool_name = ""
            alloc_mode = "static" # Default
            
            match_pool = re.search(r'vlanns-\[(.+?)\]-([a-z]+)/', dn)
            if match_pool:
                pool_name = match_pool.group(1)
                alloc_mode = match_pool.group(2)
            else:
                # Fallback si le format est différent (ex: sans crochets ?)
                match_pool_simple = re.search(r'vlanns-([^/]+)-([a-z]+)/', dn)
                if match_pool_simple:
                    pool_name = match_pool_simple.group(1)
                    alloc_mode = match_pool_simple.group(2)

            row_data = {
                'pool': pool_name,
                'pool_allocation_mode': alloc_mode,
                'block_start': attr.get('from', '').replace('vlan-', ''),
                'block_end': attr.get('to', '').replace('vlan-', ''),
                'allocation_mode': attr.get('allocMode'),
                'description': attr.get('descr'),
                'block_name': attr.get('name')
            }
            
            rows.append(row_data)
                
        return rows
