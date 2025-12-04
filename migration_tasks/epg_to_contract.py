# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class EpgToContractTask(BaseTask):
    """
    Tâche spécifique pour 'epg_to_contract'.
    Gère fvAEPg et ses enfants fvRsCons (consumer) et fvRsProv (provider).
    """
    
    def extract(self):
        # On cherche les EPGs pour avoir le contexte (Tenant, AP, EPG)
        self.aci_class = 'fvAEPg'
        super().extract()

    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            dn = attr.get('dn', '')
            
            # DN: uni/tn-[tenant]/ap-[ap]/epg-[epg]
            tenant = ""
            match_tn = re.search(r'/tn-([^/]+)/', dn)
            if match_tn: tenant = match_tn.group(1)
            
            ap = ""
            match_ap = re.search(r'/ap-([^/]+)/', dn)
            if match_ap: ap = match_ap.group(1)
            
            epg = attr.get('name')
            
            children = obj.get('children', [])
            for child in children:
                # Consumer
                if 'fvRsCons' in child:
                    c_attr = child['fvRsCons']['attributes']
                    contract_name = c_attr.get('tnVzBrCPName')
                    if contract_name:
                        row_data = {
                            'tenant': tenant,
                            'ap': ap,
                            'epg': epg,
                            'contract': contract_name,
                            'contract_type': 'consumer'
                        }
                        rows.append(row_data)
                
                # Provider
                if 'fvRsProv' in child:
                    p_attr = child['fvRsProv']['attributes']
                    contract_name = p_attr.get('tnVzBrCPName')
                    if contract_name:
                        row_data = {
                            'tenant': tenant,
                            'ap': ap,
                            'epg': epg,
                            'contract': contract_name,
                            'contract_type': 'provider'
                        }
                        rows.append(row_data)
                
        return rows
