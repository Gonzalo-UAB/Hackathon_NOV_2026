import pandas as pd
import os

def read_csv_auto(filepath):
    if not os.path.exists(filepath):
        return None
    try:
        return pd.read_csv(filepath, sep=None, engine='python')
    except Exception as e:
        print(f"Error al leer {filepath}: {e}")
        return None

print("Cargando datos para resolver el Nivel 5.2...")
aules = read_csv_auto("aules.csv")
sessions = read_csv_auto("sessions.csv")

# Intentamos cargar primero la salida del 5.1 (proposta-aules-s2.csv o proposta-aules.csv)
proposta = read_csv_auto("proposta-aules-s2.csv")
if proposta is None:
    proposta = read_csv_auto("proposta-aules.csv")
if proposta is None:
    print("⚠️ No se ha encontrado la propuesta del 5.1. Usando 'proposta_partida.csv'...")
    proposta = read_csv_auto("proposta_partida.csv")

# Cruce de información
df = pd.merge(proposta, sessions[['id_sessio', 'semestre', 'alumnes', 'tipus', 'torn_requerit', 'titulacions_curs', 'grup']], on='id_sessio', how='left')
df = pd.merge(df, aules[['aula', 'capacitat', 'ordinaria']], on='aula', how='left')

franjas_mati = ['08:00', '08:30', '09:00', '09:30', '10:30', '11:30', '12:00', '12:30', '13:15', '13:30', '14:00', '14:30']
franjas_tarda = ['15:00', '16:00', '16:30', '17:00', '18:00', '18:15', '19:00', '19:15']
dias_semana = ['L', 'M', 'X', 'J', 'V']

def get_torn_actual(h_ini):
    return 'mati' if h_ini in franjas_mati else 'tarda'

df['torn_actual'] = df['h_ini'].apply(get_torn_actual)

print("Analizando reglas de negocio para el 2º semestre...")
df_s2 = df[df['semestre'].astype(str).str.contains('2')].copy()
df_s2['titulacions_curs'] = df_s2['titulacions_curs'].fillna('')

mask_plab = df_s2['tipus'] == 'PLAB'
mask_intocables_graus = df_s2['titulacions_curs'].str.contains(r'(?:GEI|GEET|GEST).*(?:1r|2n)', regex=True, na=False)
mask_intocables = mask_plab | mask_intocables_graus

mask_moure = (df_s2['torn_actual'] != df_s2['torn_requerit']) & (~mask_intocables)

sesiones_a_mover = df_s2[mask_moure].copy()
horario_fijo = df_s2[~mask_moure].copy()

print(f"Sesiones del S2 fijas (intocables o ya correctas): {len(horario_fijo)}")
print(f"Sesiones a reubicar (cambio de turno): {len(sesiones_a_mover)}")

print("Reasignando horarios respetando reserva y aforos...")

aules_ocupades = horario_fijo.groupby(['dia', 'h_ini'])['aula'].apply(set).to_dict()
grups_ocupats = horario_fijo.groupby(['dia', 'h_ini'])['grup'].apply(set).to_dict()

aules_ord_df = aules[aules['ordinaria'] == 1].sort_values('capacitat')
aules_list = aules_ord_df.to_dict('records')
total_aules_disp = len(aules_list)

nuevas_asignaciones = []

for _, sessio in sesiones_a_mover.iterrows():
    assignada = False
    franjas_objectiu = franjas_mati if sessio['torn_requerit'] == 'mati' else franjas_tarda
    alumnes_req = sessio['alumnes']
    grup_req = sessio['grup']
    id_sessio = sessio['id_sessio']
    
    for dia in dias_semana:
        if assignada: break
        for hora in franjas_objectiu:
            if assignada: break
            
            clau_temps = (dia, hora)
            ocupadas_ahora = aules_ocupades.get(clau_temps, set())
            grupos_ahora = grups_ocupats.get(clau_temps, set())
            
            if grup_req in grupos_ahora:
                continue
                
            ord_ocupadas_ahora = len([a for a in ocupadas_ahora if a in [a_d['aula'] for a_d in aules_list]])
            
            # Regla de reserva: deben quedar al menos 2 aulas libres
            if (total_aules_disp - ord_ocupadas_ahora) <= 2:
                continue
                
            for aula_dict in aules_list:
                aula_id = aula_dict['aula']
                if aula_id not in ocupadas_ahora:
                    if aula_dict['capacitat'] >= alumnes_req:
                        nuevas_asignaciones.append({
                            'id_sessio': id_sessio,
                            'dia': dia,
                            'h_ini': hora,
                            'aula': aula_id
                        })
                        aules_ocupades.setdefault(clau_temps, set()).add(aula_id)
                        grups_ocupats.setdefault(clau_temps, set()).add(grup_req)
                        assignada = True
                        break

df_nuevas = pd.DataFrame(nuevas_asignaciones)

if not df_nuevas.empty:
    proposta_final = proposta[~proposta['id_sessio'].isin(df_nuevas['id_sessio'])].copy()
    proposta_final = pd.concat([proposta_final, df_nuevas], ignore_index=True)
else:
    proposta_final = proposta.copy()

proposta_final[['id_sessio', 'dia', 'h_ini', 'aula']].to_csv('proposta-torns.csv', index=False)
print("✅ Archivo 'proposta-torns.csv' generado exitosamente.")

print("\n" + "="*50)
print("📊 RESUMEN PARA LA JUNTA PERMANENT (5.2)")
print("="*50)

df_informe = pd.merge(proposta_final, sessions[['id_sessio', 'semestre']], on='id_sessio', how='left')
df_informe = df_informe[df_informe['semestre'].astype(str).str.contains('2')]
df_informe['torn'] = df_informe['h_ini'].apply(get_torn_actual)

pic_mati = df_informe[df_informe['torn'] == 'mati'].groupby(['dia', 'h_ini']).size().max()
pic_tarda = df_informe[df_informe['torn'] == 'tarda'].groupby(['dia', 'h_ini']).size().max()
total_aules_ordinaries = total_aules_disp - 2

print(f"1. Pico de sesiones simultáneas:")
print(f"   - Matí: {pic_mati} sessions (Màxim aules disponibles: {total_aules_ordinaries})")
print(f"   - Tarda: {pic_tarda} sessions (Màxim aules disponibles: {total_aules_ordinaries})")

if pic_mati > total_aules_ordinaries or pic_tarda > total_aules_ordinaries:
    print("\n2. Estat d'aules per mida:\n   ⚠️ Falten aules per cobrir els pics màxims amb les restriccions actuals.")
else:
    print(f"\n2. Estat d'aules per mida:\n   ✅ Hi ha capacitat suficient. Sobren almenys {total_aules_ordinaries - max(pic_mati, pic_tarda)} aules en els pics.")

print("\n3. Sessions mogudes per titulació i curs:")
if not df_nuevas.empty:
    movidas_info = pd.merge(df_nuevas['id_sessio'], df_s2[['id_sessio', 'titulacions_curs']], on='id_sessio')
    resumen_movidas = movidas_info['titulacions_curs'].value_counts()
    for tit, count in resumen_movidas.items():
        print(f"   - {tit}: {count} sessions mogudes")
else:
    print("   - Cap sessió moguda.")

print("\n4. Excepcions sol·licitades a la Regla 1 (Torns):")
no_asignadas = len(sesiones_a_mover) - len(df_nuevas)
if no_asignadas > 0:
    print(f"   ⚠️ Es sol·licita excepció per a {no_asignadas} sessions que no han cabut en el seu torn requerit.")
else:
    print("   ✅ Cap. Totes les sessions requerides s'han pogut migrar correctament.")
print("="*50)