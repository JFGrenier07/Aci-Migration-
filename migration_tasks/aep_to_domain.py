# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class AepToDomainTask(BaseTask):
    """
    Tâche spécifique pour 'aep_to_domain'.
    Gère infraRsDomP et extrait l'AEP parent et le type de domaine.
    """
    
    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            tDn = attr.get('tDn', '')
            
            # DN: uni/infra/attentp-[AEP]/rsdomP-[tDn]
            aep = ""
            match_aep = re.search(r'/attentp-([^/]+)/', dn)
            if match_aep:
                aep = match_aep.group(1)
                
            # Domain & Type from tDn
            # Ex: uni/phys-Prod_PhysDomain -> domain=Prod_PhysDomain, type=phys
            # Ex: uni/l3dom-L3_Domain -> domain=L3_Domain, type=l3dom
            # Ex: uni/vmmp-VMware/dom-MyVMM -> domain=MyVMM, type=vmm, vm_provider=VMware
            
            domain = ""
            domain_type = ""
            vm_provider = ""
            
            if '/phys-' in tDn:
                domain_type = 'phys'
                match = re.search(r'/phys-([^/]+)', tDn)
                if match: domain = match.group(1)
            elif '/l3dom-' in tDn:
                domain_type = 'l3dom'
                match = re.search(r'/l3dom-([^/]+)', tDn)
                if match: domain = match.group(1)
            elif '/l2dom-' in tDn:
                domain_type = 'l2dom'
                match = re.search(r'/l2dom-([^/]+)', tDn)
                if match: domain = match.group(1)
            elif '/vmmp-' in tDn:
                domain_type = 'vmm'
                # uni/vmmp-[provider]/dom-[domain]
                match_prov = re.search(r'/vmmp-([^/]+)/', tDn)
                if match_prov: vm_provider = match_prov.group(1)
                match_dom = re.search(r'/dom-([^/]+)', tDn)
                if match_dom: domain = match_dom.group(1)
            
            row_data = {
                'aep': aep,
                'domain': domain,
                'domain_type': domain_type,
                'vm_provider': vm_provider
            }
            
            rows.append(row_data)
                
        return rows
