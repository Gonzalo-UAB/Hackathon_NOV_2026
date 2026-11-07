import pandas as pd
import datetime
import os

def minuts_des_de_mitjanit(hora_str):
    if pd.isna(hora_str): return 0
    h, m = map(int, str(hora_str).split(':'))
    return h * 60 + m

def minuts_a_hora(minuts):
    return f"{minuts // 60:02d}:{minuts % 60:02d}"

def get_num_grup(grup_str):
    return str(grup_str).split('/')[-1]

def get_linia(tipus, num_grup_str):
    n = num_grup_str
    if tipus == 'TE':
        return n[:-1] if len(n) >= 3 and n.endswith('0') else n
    return n[:-1] if len(n) >= 3 else n

def generar_model_5_2():
    print("--- INICIANT MODEL 5.2 (CORREGIT): APLICACIÓ DE TORNS ---")
    
    # 1. Carrega de dades
    sessions = pd.read_csv('paquet/sessions.csv')
    aules = pd.read_csv('paquet/aules.csv')
    partida_5_1 = pd.read_csv('proposta-aules.csv').set_index('id_sessio')
    
    aturades = {}
    if os.path.exists('paquet/calendari.csv'):
        cal = pd.read_csv('paquet/calendari.csv')
        for _, r in cal.iterrows():
            d = r['data']
            f_ini = minuts_des_de_mitjanit(r['h_ini']) if pd.notna(r['h_ini']) else 0
            f_fi = minuts_des_de_mitjanit(r['h_fi']) if pd.notna(r['h_fi']) else 24 * 60
            if d not in aturades: aturades[d] = []
            aturades[d].append((f_ini, f_fi))
    
    aules_dict = aules.set_index('aula').to_dict('index')
    aules_docents = set(aules[aules['tipus'] == 'Aules docents']['aula'])
    
    ocupacio_aula = {}
    ocupacio_docent = {}
    ocupacio_alumnat = {} # {data: [{ini, fi, cohorts, tipus, linia, num_grup, codi}]}
    
    def registrar_ocupacio(data, ini, durada, aula, docents_str, row):
        fi = ini + durada
        
        # Ocupació aula
        if aula and pd.notna(aula):
            if data not in ocupacio_aula: ocupacio_aula[data] = {}
            if aula not in ocupacio_aula[data]: ocupacio_aula[data][aula] = []
            ocupacio_aula[data][aula].append((ini, fi))
            
        # Ocupació docents
        if pd.notna(docents_str):
            if data not in ocupacio_docent: ocupacio_docent[data] = {}
            for docent in str(docents_str).split('|'):
                if docent not in ocupacio_docent[data]: ocupacio_docent[data][docent] = []
                ocupacio_docent[data][docent].append((ini, fi))
                
        # Ocupació alumnat
        cohorts = set(x for x in str(row['titulacions_curs']).split('|') if x)
        num_g = get_num_grup(row['grup'])
        lin = get_linia(row['tipus'], num_g)
        
        if data not in ocupacio_alumnat: ocupacio_alumnat[data] = []
        ocupacio_alumnat[data].append({
            'ini': ini, 'fi': fi, 'cohorts': cohorts,
            'tipus': row['tipus'], 'linia': lin, 'num_grup': num_g, 'codi': row['codi']
        })

    def comprovar_conflictes(data, ini, durada, aula, docents_str, row):
        fi = ini + durada
        
        # R2-CALENDARI: Aturades oficials
        for a_ini, a_fi in aturades.get(data, []):
            if max(ini, a_ini) < min(fi, a_fi): return False
            
        # R4-AULA
        if aula and pd.notna(aula) and not row.get('sense_espai'):
            if aula in ocupacio_aula.get(data, {}):
                for (o_ini, o_fi) in ocupacio_aula[data][aula]:
                    if max(ini, o_ini) < min(fi, o_fi): return False
                    
        # R4-DOCENT
        if pd.notna(docents_str):
            for docent in str(docents_str).split('|'):
                if docent in ocupacio_docent.get(data, {}):
                    for (o_ini, o_fi) in ocupacio_docent[data][docent]:
                        if max(ini, o_ini) < min(fi, o_fi): return False
                        
        # R4-ALUMNAT i R4-PLAB
        cohorts = set(x for x in str(row['titulacions_curs']).split('|') if x)
        num_g = get_num_grup(row['grup'])
        lin = get_linia(row['tipus'], num_g)
        
        for o in ocupacio_alumnat.get(data, []):
            if max(ini, o['ini']) < min(fi, o['fi']):
                # Comprovació PLAB
                tipus_set = {row['tipus'], o['tipus']}
                if row['codi'] == o['codi'] and 'PLAB' in tipus_set and tipus_set & {'TE', 'PAUL'}:
                    return False
                
                # Comprovació alumnat
                if cohorts & o['cohorts']:
                    if row['tipus'] == 'TE' or o['tipus'] == 'TE':
                        if lin == o['linia'] or num_g == o['num_grup']: return False
                    else:
                        if num_g == o['num_grup']: return False
                        
        # R8-RESERVA
        if aula in aules_docents and not row.get('sense_espai'):
            aules_lliures = 0
            ocupacio_actual_data = ocupacio_aula.get(data, {})
            for a_ord in aules_docents:
                if a_ord == aula: continue
                solapa = False
                if a_ord in ocupacio_actual_data:
                    for (o_ini, o_fi) in ocupacio_actual_data[a_ord]:
                        if max(ini, o_ini) < min(fi, o_fi):
                            solapa = True
                            break
                if not solapa: aules_lliures += 1
            if aules_lliures < 2: return False
            
        return True

    sessions_2n = sessions[sessions['semestre'] == 'C/2'].copy()
    sessions_a_mantenir = []
    activitats_a_modificar = {}
    
    for idx, row in sessions_2n.iterrows():
        id_sessio = row['id_sessio']
        if id_sessio not in partida_5_1.index: continue
        
        assignacio_5_1 = partida_5_1.loc[id_sessio]
        h_ini_actual = assignacio_5_1['h_ini']
        dia_actual = assignacio_5_1['dia']
        aula_actual = assignacio_5_1['aula']
        
        # R1-FIXADA / R7-PLAB: Blindatge total de fixades.
        es_immutable = (row['tipus'] == 'PLAB') or pd.notna(row['fixada'])
        if es_immutable:
            h_ini_actual = row['h_ini']
            dia_actual = row['dia']
            if pd.notna(row['aula_partida']) and str(row['aula_partida']).strip():
                aula_actual = row['aula_partida']
        
        min_ini = minuts_des_de_mitjanit(h_ini_actual)
        es_mati = min_ini < minuts_des_de_mitjanit('14:30')
        requereix_mati = row['torn_requerit'] == 'mati'
        requereix_tarda = row['torn_requerit'] == 'tarda'
        incompleix_r1 = (requereix_mati and not es_mati) or (requereix_tarda and es_mati)
        
        if incompleix_r1 and not es_immutable:
            # R4-COMPARTIDA: Agrupem prioritariament per id_compartida
            val = row.get('id_compartida')
            grup_key = str(val).strip() if pd.notna(val) and str(val).strip() and str(val).lower() != 'nan' else str(row['activitat_id'])
            
            if grup_key not in activitats_a_modificar:
                activitats_a_modificar[grup_key] = []
            
            row_mod = row.copy()
            row_mod['aula_original_51'] = aula_actual
            row_mod['h_ini_original_51'] = h_ini_actual
            row_mod['dia_original_51'] = dia_actual
            activitats_a_modificar[grup_key].append(row_mod)
        else:
            row_mantenir = row.copy()
            sessions_a_mantenir.append((row_mantenir, h_ini_actual, dia_actual, aula_actual))
            
    proposta_final = []
    
    # Registrem les immutables / sense modificar
    for row, h_ini, dia, aula in sessions_a_mantenir:
        ini = minuts_des_de_mitjanit(h_ini)
        durada = int(row['durada_min'])
        registrar_ocupacio(row['data'], ini, durada, aula, row['docents'], row)
        
        proposta_final.append({
            'id_sessio': row['id_sessio'],
            'dia': dia,
            'h_ini': h_ini,
            'aula': aula if pd.notna(aula) else ""
        })

    franges_mati = [minuts_des_de_mitjanit(f"{h}:30") for h in range(8, 14)]
    franges_tarda = [minuts_des_de_mitjanit(f"{h}:30") for h in range(14, 20)]
    aules_ord = aules.sort_values('capacitat').to_dict('records')
    
    for grup_key, llista_sessions in activitats_a_modificar.items():
        sessio_base = llista_sessions[0]
        torn_obj = sessio_base['torn_requerit']
        durada = int(sessio_base['durada_min'])
        
        franges_candidates = franges_mati if torn_obj == 'mati' else franges_tarda
        assignat_amb_exit = False
        
        for franja_cand in franges_candidates:
            for aula_info in aules_ord:
                cand_aula = aula_info['aula']
                
                # R3-TIPUS i R3-AFORAMENT
                alumnes = int(sessio_base['alumnes']) if pd.notna(sessio_base['alumnes']) else 0
                if aula_info['capacitat'] < alumnes and not sessio_base.get('sense_espai'): continue
                
                tipus_sess = sessio_base['tipus']
                a_tipus = aula_info['tipus']
                a_desc = str(aula_info.get('descripcio', '')).lower()
                
                if tipus_sess == 'PAUL':
                    valid_espai = a_tipus in ['Aules docents', 'Seminaris', 'Aules informàtiques'] or (a_tipus == 'Laboratoris docents' and 'integrat' in a_desc)
                    if not valid_espai: continue
                elif tipus_sess == 'PLAB':
                    if a_tipus not in ['Laboratoris docents', 'Aules informàtiques']: continue
                else: # TE, SEM
                    if a_tipus not in ['Aules docents', 'Seminaris']: continue
                
                es_valid = True
                for sess in llista_sessions:
                    if not comprovar_conflictes(sess['data'], franja_cand, durada, cand_aula, sess['docents'], sess):
                        es_valid = False
                        break
                
                if es_valid:
                    for sess in llista_sessions:
                        registrar_ocupacio(sess['data'], franja_cand, durada, cand_aula, sess['docents'], sess)
                        proposta_final.append({
                            'id_sessio': sess['id_sessio'],
                            'dia': sess['dia_original_51'], # Es manté el dia setmanal
                            'h_ini': minuts_a_hora(franja_cand),
                            'aula': cand_aula if not sess.get('sense_espai') else ""
                        })
                    assignat_amb_exit = True
                    break
            
            if assignat_amb_exit: break
            
        # R5-FALTA Fallback
        if not assignat_amb_exit:
            for sess in llista_sessions:
                ini_orig = minuts_des_de_mitjanit(sess['h_ini_original_51'])
                registrar_ocupacio(sess['data'], ini_orig, int(sess['durada_min']), sess['aula_original_51'], sess['docents'], sess)
                proposta_final.append({
                    'id_sessio': sess['id_sessio'],
                    'dia': sess['dia_original_51'],
                    'h_ini': sess['h_ini_original_51'],
                    'aula': sess['aula_original_51'] if pd.notna(sess['aula_original_51']) else ""
                })

    df_final = pd.DataFrame(proposta_final).sort_values('id_sessio')
    
    # Save output and return
    df_final.to_csv('resultat_model_5_2.csv', index=False)
    print("--- MODEL 5.2 FINALITZAT ---")
    return df_final

if __name__ == '__main__':
    # Exemple d'ús si el vols córrer
    df_resultat = generar_model_5_2()
