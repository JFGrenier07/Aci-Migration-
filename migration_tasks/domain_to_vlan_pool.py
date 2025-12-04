# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class DomainToVlanPoolTask(BaseTask):
    """
    Tâche spécifique pour 'domain_to_vlan_pool'.
    Gère l'extraction du domaine parent depuis le DN.
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            tDn = attr.get('tDn', '')
            
            # Extraction du pool
            # Extraction du pool
            pool_name = ""
            # Essayer avec crochets: uni/infra/vlanns-[PoolName]-static
            match_pool = re.search(r'vlanns-\[(.+?)\]', tDn)
            if match_pool:
                pool_name = match_pool.group(1)
            else:
                # Essayer sans crochets: uni/infra/vlanns-PoolName-static
                # Attention au suffixe -static or -dynamic
                match_pool_simple = re.search(r'vlanns-([^/]+)-(static|dynamic)', tDn)
                if match_pool_simple:
                    pool_name = match_pool_simple.group(1)
            
            # Si toujours vide, prendre tout après vlanns-
            if not pool_name and 'vlanns-' in tDn:
                 match_fallback = re.search(r'vlanns-([^/]+)', tDn)
                 if match_fallback: pool_name = match_fallback.group(1)
            
            # Extraction du domaine et type
            domain = ""
            domain_type = ""
            
            # Physical Domain: uni/phys-[phys_dom]/rsvlanNs-[...]
            if '/phys-' in dn:
                match = re.search(r'/phys-([^/]+)/', dn)
                if match:
                    domain = match.group(1)
                    domain_type = 'phys'
            
            # L3 Domain: uni/l3dom-[l3_dom]/rsvlanNs-[...]
            elif '/l3dom-' in dn:
                match = re.search(r'/l3dom-([^/]+)/', dn)
                if match:
                    domain = match.group(1)
                    domain_type = 'l3dom' # ou l3 ? Vérifier les choix Ansible
            
            # VMM Domain: uni/vm-[prov]/dom-[dom]/rsvlanNs-[...]
            elif '/vm-' in dn:
                match = re.search(r'/dom-([^/]+)/', dn)
                if match:
                    domain = match.group(1)
                    domain_type = 'vmm' # ou vmware ?
            
            # Fibre Channel: uni/fc-[dom]/...
            elif '/fc-' in dn:
                match = re.search(r'/fc-([^/]+)/', dn)
                if match:
                    domain = match.group(1)
                    domain_type = 'fc'

            row_data = {
                'domain': domain,
                'domain_type': domain_type,
                'vlan_pool': pool_name, # Le CSV attend vlan_pool
                'pool_allocation_mode': attr.get('allocMode', 'static')
            }
            
            # Filtrer si on n'a pas trouvé de domaine (ex: cas exotiques)
            if domain:
                rows.append(row_data)
                
        return rows
