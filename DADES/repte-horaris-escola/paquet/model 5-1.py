import pandas as pd
import argparse
import os

def main():
    parser = argparse.ArgumentParser(description="Assignació d'aules - Repte 5.1")
    parser.add_argument('--semestre', type=int, choices=[1, 2], default=2, 
                        help="Tria el semestre a processar (1 o 2). Per defecte: 2")
    args = parser.parse_args()
    
    semestre_str = f"C/{args.semestre}"
    print(f"--- INICIANT ASSIGNACIÓ DE ESPAIS: SEMESTRE {args.semestre} ---")

    def read_csv_auto(filepath):
        try:
            return pd.read_csv(filepath, sep=None, engine='python')
        except Exception as e:
            print(f"Error al leer {filepath}: {e}")
            return None

    sessions = read_csv_auto('sessions.csv')
    aules = read_csv_auto('aules.csv')
    
    if sessions is None or aules is None:
        print("❌ Error: No se encontraron los archivos de entrada (sessions.csv o aules.csv).")
        return

    aules_dict = aules.set_index('aula').to_dict('index')
    llista_aules = aules.sort_values('capacitat').to_dict('records')

    occupancy = {aula['aula']: {} for aula in llista_aules}
    aula_base_per_grup = {}
    assigned_proposta = []

    def hora_a_minuts(h_str):
        if pd.isna(h_str): return 0
        h, m = map(int, str(h_str).split(':'))
        return h * 60 + m

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

    # 1. Registrar ocupación previa
    for _, row in sessions.iterrows():
        aula_actual = row['aula_partida']
        if pd.notna(aula_actual) and aula_actual != "":
            bloquejar_aula(row['data'], row['h_ini'], row.get('durada_min', 60), aula_actual)
            grup = row['grup']
            if pd.notna(grup) and grup not in aula_base_per_grup and row['tipus'] in ['TE', 'PAUL']:
                aula_base_per_grup[grup] = aula_actual

    # 2. Filtrar sesiones huérfanas
    assignades_noves = 0
    sessions_a_modificar = []

    for index, row in sessions.iterrows():
        aula_actual = row['aula_partida']
        sessio_final = {
            'id_sessio': row['id_sessio'], 
            'dia': row['dia'], 
            'h_ini': row['h_ini'], 
            'aula': aula_actual if pd.notna(aula_actual) else ""
        }

        if row['semestre'] == semestre_str and pd.isna(aula_actual) and row['tipus'] != 'PLAB' and row.get('sense_espai') != 1:
            sessions_a_modificar.append((index, row))
        else:
            assigned_proposta.append(sessio_final)

    sessions_a_modificar.sort(key=lambda x: int(x[1]['alumnes']) if pd.notna(x[1]['alumnes']) else 0, reverse=True)

    # 3. Algoritmo de asignación
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
        
        if pd.notna(grup) and grup in aula_base_per_grup:
            cand = aula_base_per_grup[grup]
            if cand in aules_dict:
                info = aules_dict[cand]
                if info['tipus'] in tipus_valids and info['capacitat'] >= alumnes:
                    if comprovar_disponibilitat(data_sessio, h_ini, durada_min, cand):
                        aula_assignada = cand

        if not aula_assignada:
            for info in llista_aules:
                cand = info['aula']
                if info['tipus'] in tipus_valids and info['capacitat'] >= alumnes:
                    if comprovar_disponibilitat(data_sessio, h_ini, durada_min, cand):
                        aula_assignada = cand
                        if pd.notna(grup) and grup not in aula_base_per_grup:
                            aula_base_per_grup[grup] = cand
                        break
        
        if aula_assignada:
            bloquejar_aula(data_sessio, h_ini, durada_min, aula_assignada)
            assignades_noves += 1
            
        assigned_proposta.append({
            'id_sessio': row['id_sessio'], 
            'dia': dia, 
            'h_ini': h_ini, 
            'aula': aula_assignada
        })

    # 4. Generar archivos de salida
    df_final = pd.DataFrame(assigned_proposta).sort_values('id_sessio')
    
    # Guardamos en los dos nombres posibles para compatibilidad directa
    df_final.to_csv(f"proposta-aules-s{args.semestre}.csv", index=False)
    df_final.to_csv("proposta-aules.csv", index=False)
    
    print(f"\n--- RESUMEN FINAL (5.1) ---")
    print(f"Aulas asignadas nuevas: {assignades_noves} de {len(sessions_a_modificar)}")
    print(f"Archivos generados: 'proposta-aules-s{args.semestre}.csv' y 'proposta-aules.csv'")

if __name__ == "__main__":
    main()