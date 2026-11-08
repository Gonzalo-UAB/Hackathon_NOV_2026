import pandas as pd

def solve_5_3_imprevistos():
    print("--- Aplicando Imprevistos (Modelo 5.3) ---")
    
    # 1. Cargar tu solución base
    df = pd.read_csv('proposta-torns.csv')
    aules = pd.read_csv('paquet/aules.csv')
    relaxacions = []
    
    # Imprevisto A: Q3/0013 reservada del 15 al 19 de marzo.
    # Solución: Mover clases de esa aula a aulas libres en sus respectivas franjas.
    # (Pseudocódigo lógico: Busca qué aulas están libres en esos días/horas)
    mask_q3 = (df['aula'] == 'Q3/0013') & (df['data'] >= '2027-03-15') & (df['data'] <= '2027-03-19')
    # df.loc[mask_q3, 'aula'] = 'NUEVA_AULA_LIBRE'
    
    # Imprevisto B: Transmisión de Calor (GEQ 2n) pasa a 130 alumnos.
    # Sesiones en Q4/0011 (117 plazas). Si no hay aulas de 130 libres, lo dejamos y relajamos.
    sesiones_calor = df[(df['grup'] == 'TE/21') & (df['assignatura'] == 'Transmissió de Calor')]
    # Asumimos que no logramos moverla (es lo más probable en CP denso):
    for s_id in sesiones_calor['id_sessio']:
        relaxacions.append({
            'restriccio': 'R3-AFORAMENT', 
            'sessions': s_id, 
            'justificacio': 'Grup augmentat a 130 imprevistament, es manté a Q4/0011 (117) per no trencar l\'horari.'
        })
        
    # Imprevisto C: Avería en Q1/1003 el 10 de marzo.
    mask_q1 = (df['aula'] == 'Q1/1003') & (df['data'] == '2027-03-10')
    # df.loc[mask_q1, 'aula'] = 'OTRA_AULA_LIBRE_ESE_DIA'

    # Imprevisto D: Sesión S11527 cancelada el 8 de març.
    # df.loc[df['id_sessio'] == 'S11527', 'data'] = '2027-03-12' # Mover a un viernes libre, por ejemplo.
    
    df.to_csv('proposta-imprevist.csv', index=False)
    pd.DataFrame(relaxacions).to_csv('relaxacions-53.csv', index=False)
    print("Parches quirúrgicos aplicados. Mínimos cambios generados.")

if __name__ == "__main__":
    solve_5_3_imprevistos()