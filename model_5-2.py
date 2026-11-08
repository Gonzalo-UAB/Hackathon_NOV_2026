import pandas as pd
import os
import re

def solve_5_2_safe():
    print("--- INICIANT MODEL 5.2 (Horaris i Aules - Basat en el model segur de 84/100) ---")
    
    sessions_path = 'paquet/sessions.csv'
    aules_path = 'paquet/aules.csv'
    proposta_path = 'paquet/proposta_partida.csv'
    
    for fitxer in [sessions_path, aules_path, proposta_path]:
        if not os.path.exists(fitxer):
            print(f"❌ ERROR: No es troba '{fitxer}'.")
            return
            
    sessions_df = pd.read_csv(sessions_path)
    aules_df = pd.read_csv(aules_path)
    proposta_df = pd.read_csv(proposta_path)
    
    # Ens quedem les columnes necessàries sense duplicar
    cols_sessions = [c for c in sessions_df.columns if c not in proposta_df.columns or c == 'id_sessio']
    df = proposta_df.merge(sessions_df[cols_sessions], on='id_sessio', how='left')
    
    # ---------------------------------------------------------
    # 1. PREPARACIÓ D'ESTRUCTURES
    # ---------------------------------------------------------
    MAX_AULES = 19
    aules_docents = aules_df[aules_df['tipus'].isin(['Aules docents', 'Seminaris'])].sort_values('capacitat').to_dict('records')
    aules_dict = aules_df.set_index('aula').to_dict('index')
    
    ocupacio_aules = {a: {} for a in aules_df['aula']}
    # Control per no trencar les regles R4-DOCENT i R4-ALUMNAT en moure horaris
    ocupacio_docent = {} 
    ocupacio_grup = {}
    ocupacio_franja = {} # Quantitat d'aules usades per (dia, h_ini)
    
    slots_mati = [f"{h:02d}:30" for h in range(8, 14)]
    slots_tarda = [f"{h:02d}:30" for h in range(14, 21)]
    tots_slots = slots_mati + slots_tarda
    dies = ['dl', 'dt', 'dc', 'dj', 'dv']
    
    proposta_final = []
    relaxacions_52 = []

    def bloquejar_temps(docent, grup, dia, h_ini, req_espai):
        if pd.notna(docent):
            ocupacio_docent.setdefault(docent, set()).add((dia, h_ini))
        if pd.notna(grup):
            ocupacio_grup.setdefault(grup, set()).add((dia, h_ini))
        if req_espai:
            ocupacio_franja[(dia, h_ini)] = ocupacio_franja.get((dia, h_ini), 0) + 1

    def es_franja_valida(docent, grup, dia, h_ini, req_espai):
        if pd.notna(docent) and (dia, h_ini) in ocupacio_docent.get(docent, set()): return False
        if pd.notna(grup) and (dia, h_ini) in ocupacio_grup.get(grup, set()): return False
        if req_espai and ocupacio_franja.get((dia, h_ini), 0) >= MAX_AULES: return False
        return True

    # ---------------------------------------------------------
    # 2. FASE TEMPORAL (Assignació de dia i hora segura)
    # ---------------------------------------------------------
    # Primer passem les sessions fixades i els laboratoris per bloquejar-los
    sessions_a_ubicar = []
    for idx, row in df.iterrows():
        req_espai = row.get('sense_espai', 0) in [0, '0', False, 0.0] and row.get('tipus') != 'PLAB'
        fixada = pd.notna(row.get('fixada'))
        
        if fixada or not req_espai:
            bloquejar_temps(row['docent'], row['grup'], row['dia'], row['h_ini'], req_espai)
            sessions_a_ubicar.append((row, row['dia'], row['h_ini'], True)) # True = Ja té temps definit
        else:
            sessions_a_ubicar.append((row, None, None, False))

    # Segon pas: Ubicar la resta respectant els torns i el límit de 19
    for i, (row, dia, h_ini, definit) in enumerate(sessions_a_ubicar):
        if definit: continue
        
        req_espai = True
        torn_req = str(row.get('torn_requerit', 'mati')).lower()
        dia_orig = row['dia']
        h_orig = row['h_ini']
        docent = row.get('docent')
        grup = row.get('grup')
        
        # Intent 1: Quedar-se al seu lloc original
        if es_franja_valida(docent, grup, dia_orig, h_orig, req_espai):
            bloquejar_temps(docent, grup, dia_orig, h_orig, req_espai)
            sessions_a_ubicar[i] = (row, dia_orig, h_orig, True)
            continue
            
        # Intent 2: Buscar lloc dins del mateix torn
        slots_pref = slots_mati if torn_req == 'mati' else slots_tarda
        trobat = False
        for d in dies:
            for s in slots_pref:
                if es_franja_valida(docent, grup, d, s, req_espai):
                    bloquejar_temps(docent, grup, d, s, req_espai)
                    sessions_a_ubicar[i] = (row, d, s, True)
                    trobat = True
                    break
            if trobat: break
            
        # Intent 3 (Relaxació): Canviar de torn
        if not trobat:
            slots_alt = slots_tarda if torn_req == 'mati' else slots_mati
            for d in dies:
                for s in slots_alt:
                    if es_franja_valida(docent, grup, d, s, req_espai):
                        bloquejar_temps(docent, grup, d, s, req_espai)
                        sessions_a_ubicar[i] = (row, d, s, True)
                        relaxacions_52.append({
                            'restriccio': 'R1-TORN',
                            'sessions': row['id_sessio'],
                            'justificacio': f"Moguda a {d} {s} per límit d'aules (19) o col·lisió de docent/grup."
                        })
                        trobat = True
                        break
                if trobat: break

    # ---------------------------------------------------------
    # 3. FASE D'ESPAIS (Motor 84/100 exacte)
    # ---------------------------------------------------------
    def extreure_passadis(aula_str):
        if pd.isna(aula_str) or not isinstance(aula_str, str): return None
        match = re.match(r'^([A-Z]\d)/', aula_str)
        return match.group(1) if match else None

    estat_grups = {}
    
    for row, dia, h_ini, _ in sessions_a_ubicar:
        s_id = row['id_sessio']
        req_espai = row.get('sense_espai', 0) in [0, '0', False, 0.0] and row.get('tipus') != 'PLAB'
        alumnes = int(row['alumnes']) if pd.notna(row['alumnes']) else 0
        grup = row.get('grup')
        
        # Si no requereix espai normal, es queda com estava
        if not req_espai:
            aula = row.get('aula')
            proposta_final.append({'id_sessio': s_id, 'dia': dia, 'h_ini': h_ini, 'aula': aula if pd.notna(aula) else ""})
            continue

        # Lògica d'assignació d'aules del 84/100
        aula_assignada = None
        estat = estat_grups.get(grup, {})
        aula_te_obj = estat.get('aula_te_principal')
        passadis_obj = estat.get('passadis')
        edifici_obj = estat.get('edifici')

        def aula_lliure(cand):
            return (dia, h_ini) not in ocupacio_aules.get(cand, set())

        # P1: Aula TE principal
        if aula_te_obj in aules_dict and aules_dict[aula_te_obj]['capacitat'] >= alumnes and aula_lliure(aula_te_obj):
            aula_assignada = aula_te_obj
            
        # P2: Mateix passadís històric
        if not aula_assignada and passadis_obj:
            for info in aules_docents:
                cand = info['aula']
                if info['capacitat'] >= alumnes and extreure_passadis(cand) == passadis_obj and aula_lliure(cand):
                    aula_assignada = cand
                    break
                    
        # P3: Mateix edifici històric
        if not aula_assignada and edifici_obj:
            for info in aules_docents:
                cand = info['aula']
                if info['capacitat'] >= alumnes and info['edifici'] == edifici_obj and aula_lliure(cand):
                    aula_assignada = cand
                    break

        # P4: Primera aula vàlida (la més ajustada en aforament gràcies a l'ordenació d'aules_docents)
        if not aula_assignada:
            for info in aules_docents:
                cand = info['aula']
                if info['capacitat'] >= alumnes and aula_lliure(cand):
                    aula_assignada = cand
                    break
                    
        # P5 (Emergència): La més gran lliure encara que no hi càpiguen (Relaxació Aforament)
        if not aula_assignada:
            for info in reversed(aules_docents):
                cand = info['aula']
                if aula_lliure(cand):
                    aula_assignada = cand
                    relaxacions_52.append({
                        'restriccio': 'R3-AFORAMENT',
                        'sessions': s_id,
                        'justificacio': f"Aforament superat per a {alumnes} alumnes a {cand}."
                    })
                    break

        if aula_assignada:
            ocupacio_aules[aula_assignada].setdefault((dia, h_ini), True)
            
            # Actualitzar historial del grup per les prioritats de les següents classes
            if pd.notna(grup):
                if grup not in estat_grups:
                    estat_grups[grup] = {'edifici': aules_dict[aula_assignada]['edifici'], 
                                         'passadis': extreure_passadis(aula_assignada), 
                                         'aula_te_principal': None}
                if row.get('tipus') in ['TE', 'PAUL'] and estat_grups[grup]['aula_te_principal'] is None:
                    estat_grups[grup]['aula_te_principal'] = aula_assignada

        proposta_final.append({'id_sessio': s_id, 'dia': dia, 'h_ini': h_ini, 'aula': aula_assignada if aula_assignada else ""})

    # ---------------------------------------------------------
    # 4. GUARDAR RESULTATS
    # ---------------------------------------------------------
    df_final = pd.DataFrame(proposta_final)[['id_sessio', 'dia', 'h_ini', 'aula']].sort_values('id_sessio')
    df_final.to_csv("proposta-horaris-52.csv", index=False)
    
    if relaxacions_52:
        pd.DataFrame(relaxacions_52).to_csv('relaxacions-52.csv', index=False)
    else:
        pd.DataFrame(columns=['restriccio', 'sessions', 'justificacio']).to_csv('relaxacions-52.csv', index=False)
        
    print(f"\n✅ ÈXIT! S'han processat i guardat {len(df_final)} files a 'proposta-horaris-52.csv'.")
    print(f"📊 S'han generat {len(relaxacions_52)} relaxacions automàtiques a 'relaxacions-52.csv'.")

if __name__ == "__main__":
    solve_5_2_safe()