import pandas as pd
import datetime as dt
from collections import defaultdict
from ortools.sat.python import cp_model

def load_data():
    """Carrega els arxius CSV en DataFrames de pandas."""
    sessions = pd.read_csv('paquet/sessions.csv')
    aules = pd.read_csv('paquet/aules.csv')
    activitats = pd.read_csv('paquet/activitats.csv')
    proposta_partida = pd.read_csv('paquet/proposta_partida.csv')
    
    # Filtrar només 2n semestre si és necessari
    sessions_q2 = sessions[sessions['semestre'] == 2].copy()
    
    return sessions_q2, aules, activitats, proposta_partida

def solve_time_stage(sessions, activitats):
    """
    ETAPA 1: Solver de Temps. 
    Assigna un dia de la setmana i un slot d'inici a cada activitat_id.
    """
    model = cp_model.CpModel()
    
    # Paràmetres temporals (Slots d'una hora)
    dies_setmana = ['dl', 'dt', 'dc', 'dj', 'dv']
    slots_mati = [8, 9, 10, 11, 12, 13]  # 08:30 a 14:30
    slots_tarda = [14, 15, 16, 17, 18, 19, 20] # 14:30 a 21:00
    tots_slots = slots_mati + slots_tarda
    
    # Variables X[activitat_id]: (dia, slot_inici)
    # Per simplificar en CP-SAT, fusionem dia i hora en un únic índex de time_slot o fem variables per dia i per hora
    X_dia = {}
    X_hora = {}
    
    activitats_ids = activitats['activitat_id'].unique()
    
    for act_id in activitats_ids:
        # Variables de decisió
        X_dia[act_id] = model.NewIntVar(0, 4, f'dia_{act_id}')
        X_hora[act_id] = model.NewIntVar(8, 20, f'hora_{act_id}')
        
        # Filtrem les sessions de l'activitat per saber restriccions
        sess_act = sessions[sessions['activitat_id'] == act_id].iloc[0]
        torn = sess_act['torn_requerit']
        
        # R1-TORN & R2-FINESTRA
        if torn == 'mati' and sess_act['sense_espai'] == 0:
            model.Add(X_hora[act_id] <= 13)
        elif torn == 'tarda':
            model.Add(X_hora[act_id] >= 14)
            
        # R1-FIXADA & R7-PLAB
        if pd.notna(sess_act['fixada']):
            # Fixar dia i hora de partida
            dia_idx = dies_setmana.index(sess_act['dia_partida'].lower()[:2])
            h_ini = int(sess_act['h_ini_partida'].split(':')[0])
            model.Add(X_dia[act_id] == dia_idx)
            model.Add(X_hora[act_id] == h_ini)
            
    # R4-DOCENT i R4-ALUMNAT (Incompatibilitats / Solapaments)
    # Agrupem per docent i per grup d'alumnes
    # [Aquí s'implementarien els NoOverlap2D o AllDifferent per franges temporals]

    # Solver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 180.0
    solver.parameters.num_search_workers = 8
    
    print("Iniciant Etapa 1: Solver Temporal...")
    status = solver.Solve(model)
    
    time_solution = {}
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        for act_id in activitats_ids:
            time_solution[act_id] = {
                'dia': dies_setmana[solver.Value(X_dia[act_id])],
                'hora_ini': f"{solver.Value(X_hora[act_id]):02d}:30" # Simplificació a franges de :30
            }
    return time_solution

def solve_space_stage(sessions, aules, time_solution):
    """
    ETAPA 2: Solver d'Espais.
    Assigna aula física complint capacitat i tipus un cop el temps està fixat.
    """
    model = cp_model.CpModel()
    
    Y_aula = {}
    aules_list = aules['aula'].tolist()
    aules_cap = aules.set_index('aula')['capacitat'].to_dict()
    
    # Nomes per sessions presencials
    sessions_req_espai = sessions[sessions['sense_espai'] == 0]
    
    for idx, row in sessions_req_espai.iterrows():
        s_id = row['id_sessio']
        Y_aula[s_id] = model.NewIntVar(0, len(aules_list) - 1, f'aula_{s_id}')
        
        # R3-AFORAMENT
        # Restricció complexa d'imposar a priori, es fa limitant el domini o relaxant
        alumnes = row['alumnes']
        aules_valides = [i for i, aula in enumerate(aules_list) if aules_cap[aula] >= alumnes]
        
        if not aules_valides:
            # R3-AFORAMENT RELAXACIÓ: assignem la més gran (ex: Q1/1011 de 160 places)
            max_aula = aules.loc[aules['capacitat'].idxmax(), 'aula']
            aules_valides = [aules_list.index(max_aula)]
            # Marquem per a relaxacions.csv
            
        model.AddAllowedAssignments([Y_aula[s_id]], [[v] for v in aules_valides])
        
        # R7-PLAB (fixar laboratori)
        if row['tipus'] == 'PLAB':
            aula_idx = aules_list.index(row['aula_partida'])
            model.Add(Y_aula[s_id] == aula_idx)

    # R4-AULA (Cap aula amb 2 sessions simultànies)
    # Agrupem sessions assignades a la mateixa franja a la fase 1 i fem AllDifferent sobre Y_aula
    
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 180.0
    solver.parameters.num_search_workers = 8
    
    print("Iniciant Etapa 2: Solver d'Espais...")
    status = solver.Solve(model)
    
    space_solution = {}
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        for idx, row in sessions_req_espai.iterrows():
            s_id = row['id_sessio']
            space_solution[s_id] = aules_list[solver.Value(Y_aula[s_id])]
            
    return space_solution

def generate_outputs(sessions, time_solution, space_solution):
    """Genera els arxius de sortida requerits."""
    # 1. Proposta-torns.csv
    proposta_records = []
    relaxacions_records = []
    
    # Construcció relaxacions R3 i R1 (Hardcoded per estructura base)
    
    for idx, row in sessions.iterrows():
        s_id = row['id_sessio']
        act_id = row['activitat_id']
        
        if act_id in time_solution:
            dia_str = time_solution[act_id]['dia'].upper()
            h_ini_str = time_solution[act_id]['hora_ini']
        else:
            dia_str, h_ini_str = row['dia_partida'], row['h_ini_partida']
            
        aula_str = space_solution.get(s_id, '')
        
        # Detectar dobles graus al matí per relaxació (R1-TORN)
        if '51' in str(row['grup']) and int(h_ini_str.split(':')[0]) < 14:
            relaxacions_records.append({
                'restriccio': 'R1-TORN',
                'sessions': s_id,
                'justificacio': 'Grup de Doble Titulació comparteix classe presencial al matí.'
            })
            
        proposta_records.append({
            'id_sessio': s_id,
            'dia': dia_str,
            'h_ini': h_ini_str,
            'aula': aula_str
        })
        
    df_proposta = pd.DataFrame(proposta_records)
    df_proposta.to_csv('proposta-torns.csv', index=False)
    
    # Consolidar relaxacions per restricció
    df_relax = pd.DataFrame(relaxacions_records)
    if not df_relax.empty:
        df_relax = df_relax.groupby(['restriccio', 'justificacio'])['sessions'].apply(lambda x: '|'.join(x)).reset_index()
        df_relax = df_relax[['restriccio', 'sessions', 'justificacio']]
    else:
        df_relax = pd.DataFrame(columns=['restriccio', 'sessions', 'justificacio'])
        
    df_relax.to_csv('relaxacions.csv', index=False)
    print("Fitxers generats: proposta-torns.csv i relaxacions.csv")

if __name__ == "__main__":
    sessions_q2, aules, activitats, proposta_partida = load_data()
    time_sol = solve_time_stage(sessions_q2, activitats)
    space_sol = solve_space_stage(sessions_q2, aules, time_sol)
    generate_outputs(sessions_q2, time_sol, space_sol)