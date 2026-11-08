import pandas as pd
import argparse
import os
import re

def main():
    parser = argparse.ArgumentParser(description="Assignació d'aules - Repte 5.1 i 5.2")
    parser.add_argument('--semestre', type=int, choices=[1, 2], default=2, 
                        help="Tria el semestre a processar (1 o 2). Per defecte: 2")
    args = parser.parse_args()
    
    semestre_str = f"C/{args.semestre}"
    print(f"--- INICIANT ASSIGNACIÓ DE ESPAIS: SEMESTRE {args.semestre} (Amb Optimització R9) ---")

    def read_csv_auto(filepath):
        try:
            return pd.read_csv(filepath, sep=None, engine='python')
        except Exception as e:
            print(f"Error al llegir {filepath}: {e}")
            return None

    # Ajustem la ruta a 'data' o al directori arrel segons disponibilitat
    sessions_path = 'paquet/sessions.csv' if os.path.exists('paquet/sessions.csv') else 'sessions.csv'
    aules_path = 'paquet/aules.csv' if os.path.exists('paquet/aules.csv') else 'aules.csv'
    
    sessions = read_csv_auto(sessions_path)
    aules = read_csv_auto(aules_path)
    
    if sessions is None or aules is None:
        print("❌ Error: No s'han trobat els arxius d'entrada.")
        return

    aules_dict = aules.set_index('aula').to_dict('index')
    llista_aules = aules.sort_values('capacitat').to_dict('records')

    occupancy = {aula['aula']: {} for aula in llista_aules}
    
    # Nou diccionari per optimitzar r6 (Passadís) i r9 (Desplaçaments)
    # L'estructura serà: {grup: {'edifici': 'Q', 'passadis': 'Q6', 'aula_te_principal': 'Q6/1012', 'totes_aules': set()}}
    estat_grups = {}
    assigned_proposta = []

    def hora_a_minuts(h_str):
        if pd.isna(h_str): return 0
        h, m = map(int, str(h_str).split(':'))
        return h * 60 + m

    def extreure_passadis(aula_str):
        if pd.isna(aula_str) or not isinstance(aula_str, str): return None
        # Captura Espina + Barra + Planta (ex: 'Q4/1')
        match = re.match(r'^([A-Z]\d/\d)', aula_str) 
        return match.group(1) if match else None

    def bloquejar_aula(data_sessio, h_ini_str, durada_min, aula):
        if pd.isna(aula) or not aula or aula not in occupancy: return
        ini = hora_a_minuts(h_ini_str)
        durada = int(durada_min) if pd.notna(durada_min) else 60
        fi = ini + durada
        
        if data_sessio not in occupancy[aula]:
            occupancy[aula][data_sessio] = []
        occupancy[aula][data_sessio].append((ini, fi))

    def comprovar_disponibilitat(data_sessio, h_ini_str, durada_min, aula):
        if aula not in occupancy: return False
        ini = hora_a_minuts(h_ini_str)
        durada = int(durada_min) if pd.notna(durada_min) else 60
        fi = ini + durada
        
        if data_sessio in occupancy[aula]:
            for (o_ini, o_fi) in occupancy[aula][data_sessio]:
                if max(ini, o_ini) < min(fi, o_fi):
                    return False
        return True

    def actualitzar_estat_grup(grup, aula, tipus_sessio):
        if pd.isna(grup) or not grup: return
        if pd.isna(aula) or aula not in aules_dict: return
        
        if grup not in estat_grups:
            estat_grups[grup] = {
                'edifici': aules_dict[aula]['edifici'],
                'passadis': extreure_passadis(aula),
                'aula_te_principal': None,
                'aules_usades': set()
            }
        
        estat_grups[grup]['aules_usades'].add(aula)
        
        if tipus_sessio in ['TE', 'PAUL'] and estat_grups[grup]['aula_te_principal'] is None:
            estat_grups[grup]['aula_te_principal'] = aula

    def es_aula_valida(row, aula):
        if pd.isna(aula) or not aula or aula not in aules_dict:
            return False
            
        info = aules_dict[aula]
        tipus_sessio = row['tipus']
        alumnes = int(row['alumnes']) if pd.notna(row['alumnes']) else 0
        
        tipus_valids = ['Aules docents', 'Seminaris']
        if tipus_sessio == 'PAUL':
            tipus_valids.extend(['Aules informàtiques'])
        elif tipus_sessio not in ['TE', 'PAUL', 'SEM']:
            tipus_valids = ['Aules docents']
            
        if info['tipus'] not in tipus_valids:
            return False
            
        if info['capacitat'] < alumnes:
            return False
            
        return True

    # 1. Separar sessions a mantenir i sessions a modificar
    sessions_a_modificar = []
    sessions_a_mantenir = []
    
    # Sortim per dia, grup i hora per processar consecutivament i minimitzar desplaçaments
    sessions_sorted = sessions.sort_values(['data', 'grup', 'h_ini'])
    
    for index, row in sessions_sorted.iterrows():
        aula_actual = row['aula_partida']
        
        if row['tipus'] != 'PLAB' and row.get('sense_espai') != 1:
            manca_aula = pd.isna(aula_actual) or str(aula_actual).strip() == ""
            if manca_aula or (row['semestre'] == semestre_str and not es_aula_valida(row, aula_actual)):
                sessions_a_modificar.append((index, row))
                continue
                
        sessions_a_mantenir.append(row)

    # 2. Registrar ocupació PRÈVIA i extreure informació dels grups (per R9)
    for row in sessions_a_mantenir:
        aula_actual = row['aula_partida']
        if pd.notna(aula_actual) and str(aula_actual).strip() != "":
            bloquejar_aula(row['data'], row['h_ini'], row.get('durada_min', 60), aula_actual)
            actualitzar_estat_grup(row['grup'], aula_actual, row['tipus'])
                
        assigned_proposta.append({
            'id_sessio': row['id_sessio'], 
            'dia': row['dia'], 
            'h_ini': row['h_ini'], 
            'aula': aula_actual if pd.notna(aula_actual) else ""
        })

    # Ordenem per tractar les aules més restrictives (amb més alumnes) primer, però preservant l'agrupació per dia
    sessions_a_modificar.sort(key=lambda x: (x[1]['data'], x[1]['grup'], int(x[1]['alumnes']) if pd.notna(x[1]['alumnes']) else 0), reverse=True)

    # 3. Algoritme d'assignació optimitzat per a la R9
    assignades_noves = 0
    for index, row in sessions_a_modificar:
        alumnes = int(row['alumnes']) if pd.notna(row['alumnes']) else 0
        grup = row['grup']
        tipus_sessio = row['tipus']
        durada_min = row.get('durada_min', 60)
        data_sessio = row['data']
        dia = row['dia']
        h_ini = row['h_ini']
        
        tipus_valids = ['Aules docents', 'Seminaris']
        if tipus_sessio == 'PAUL':
            tipus_valids.extend(['Aules informàtiques'])
        elif tipus_sessio not in ['TE', 'PAUL', 'SEM']:
            tipus_valids = ['Aules docents']
            
        aula_assignada = ""
        estat = estat_grups.get(grup, {})
        edifici_obj = estat.get('edifici')
        passadis_obj = estat.get('passadis')
        aula_te_obj = estat.get('aula_te_principal')
        aules_usades = estat.get('aules_usades', set())

        # Funció per avaluar un candidat
        def avaluar_candidat(cand_aula, info_aula):
            if info_aula['tipus'] not in tipus_valids or info_aula['capacitat'] < alumnes:
                return False
            return comprovar_disponibilitat(data_sessio, h_ini, durada_min, cand_aula)

        # PRIORITAT 1: Repetir la mateixa aula TE principal del grup (Minimitza desplaçaments aula i aules_extra_per_grup)
        if not aula_assignada and aula_te_obj in aules_dict:
            if avaluar_candidat(aula_te_obj, aules_dict[aula_te_obj]):
                aula_assignada = aula_te_obj

        # PRIORITAT 2: Reutilitzar qualsevol aula que ja hagi utilitzat el grup (Minimitza aules extra)
        if not aula_assignada:
            for aula_usada in aules_usades:
                if aula_usada in aules_dict and avaluar_candidat(aula_usada, aules_dict[aula_usada]):
                    aula_assignada = aula_usada
                    break

        # PRIORITAT 3: Aula al MATEIX PASSADÍS (Minimitza canvis de passadís TE/PAUL i assegura mateix edifici)
        if not aula_assignada and passadis_obj:
            for info in llista_aules:
                cand = info['aula']
                if info['edifici'] == edifici_obj and extreure_passadis(cand) == passadis_obj:
                    if avaluar_candidat(cand, info):
                        aula_assignada = cand
                        break

        # PRIORITAT 4: Aula al MATEIX EDIFICI (Mantingues desplacaments_edifici a 0)
        if not aula_assignada and edifici_obj:
            for info in llista_aules:
                cand = info['aula']
                if info['edifici'] == edifici_obj:
                    if avaluar_candidat(cand, info):
                        aula_assignada = cand
                        break

        # PRIORITAT 5: Primera aula completament compatible
        if not aula_assignada:
            for info in llista_aules:
                cand = info['aula']
                if avaluar_candidat(cand, info):
                    aula_assignada = cand
                    break
        
        # PRIORITAT 6 (FALLBACK): Capacitat insuficient però tipus correcte (agafem la més gran del mateix edifici)
        if not aula_assignada and edifici_obj:
            for info in reversed(llista_aules):
                cand = info['aula']
                if info['tipus'] in tipus_valids and info['edifici'] == edifici_obj:
                    if comprovar_disponibilitat(data_sessio, h_ini, durada_min, cand):
                        aula_assignada = cand
                        break

        # PRIORITAT 7 (FALLBACK): Capacitat insuficient però tipus correcte (qualsevol edifici)
        if not aula_assignada:
            for info in reversed(llista_aules):
                cand = info['aula']
                if info['tipus'] in tipus_valids:
                    if comprovar_disponibilitat(data_sessio, h_ini, durada_min, cand):
                        aula_assignada = cand
                        break
                        
        # PRIORITAT 8 (EMERGÈNCIA): Qualsevol lliure per salvar l'R5.
        if not aula_assignada:
            for info in reversed(llista_aules):
                cand = info['aula']
                if comprovar_disponibilitat(data_sessio, h_ini, durada_min, cand):
                    aula_assignada = cand
                    break

        if aula_assignada:
            bloquejar_aula(data_sessio, h_ini, durada_min, aula_assignada)
            actualitzar_estat_grup(grup, aula_assignada, tipus_sessio)
            assignades_noves += 1
        else:
            print(f"❌ CRÍTIC: Impossible trobar cap aula per a {row['id_sessio']}.")
            
        assigned_proposta.append({
            'id_sessio': row['id_sessio'], 
            'dia': dia, 
            'h_ini': h_ini, 
            'aula': aula_assignada
        })

    # 4. Generar arxius de sortida
    df_final = pd.DataFrame(assigned_proposta).sort_values('id_sessio')
    df_final.to_csv("proposta-aules.csv", index=False)
    
    print(f"\n--- RESUM FINAL (5.1 - Optimització) ---")
    print(f"Sessions reassignades o noves: {assignades_noves} de {len(sessions_a_modificar)}")
    print(f"Arxius generats: 'proposta-aules.csv'")

if __name__ == "__main__":
    main()