import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# ==========================================
# 1. CARGA Y PREPARACIÓN DE DATOS REALES
# ==========================================

def read_csv_auto(filepath):
    try:
        # Corregido: pd.read_csv en lugar de pd.csv
        df = pd.read_csv(filepath, sep=';')
        if len(df.columns) == 1:
             df = pd.read_csv(filepath, sep=',')
        return df
    except Exception as e:
        print(f"Error crítico al leer {filepath}: {e}")
        exit()

aules = read_csv_auto("data/aules.csv")
proposta = read_csv_auto("data/proposta_partida.csv")
sessions = read_csv_auto("data/sessions.csv")

# Cruzar los datos:
# 1. Unimos propuesta y sesiones para tener el número de alumnos ('alumnes') por sesión
df = pd.merge(proposta, sessions[['id_sessio', 'alumnes']], on='id_sessio', how='left')
# 2. Unimos con aules para obtener 'capacitat' y 'edifici'
df = pd.merge(df, aules[['aula', 'capacitat', 'edifici']], on='aula', how='left')

# Limpieza de datos
df['alumnes'] = df['alumnes'].fillna(0)
df = df.dropna(subset=['capacitat'])

# Ordenar días y horas lógicamente
orden_dias = ['L', 'M', 'X', 'J', 'V']
df['dia'] = pd.Categorical(df['dia'], categories=orden_dias, ordered=True)
df = df.sort_values(['dia', 'h_ini'])

# Configuración general
sns.set_theme(style="whitegrid")
plt.rcParams.update({'figure.max_open_warning': 0})

# ==========================================
# GRÁFICO 1: Curva de demanda horaria global
# ==========================================
plt.figure(figsize=(12, 6))
demanda_horaria = df.groupby('h_ini')['alumnes'].sum().reset_index()

sns.lineplot(data=demanda_horaria, x='h_ini', y='alumnes', marker='o', linewidth=2.5, color='b')
plt.title('Curva de Demanda Horaria Global (Alumnos concurrentes)', fontsize=14, pad=15)
plt.xlabel('Hora de Inicio (Franja)', fontsize=12)
plt.ylabel('Volumen Total de Alumnos', fontsize=12)
plt.xticks(rotation=45)
plt.fill_between(demanda_horaria['h_ini'], demanda_horaria['alumnes'], alpha=0.2, color='b')
plt.tight_layout()
plt.savefig('1_curva_demanda_horaria.png', dpi=300)
plt.close()

# ==========================================
# GRÁFICO 2: Análisis de eficiencia de asignación
# ==========================================
plt.figure(figsize=(10, 6))
sns.scatterplot(data=df, x='capacitat', y='alumnes', hue='edifici', alpha=0.7, s=80)

max_val = max(df['capacitat'].max(), df['alumnes'].max())
plt.plot([0, max_val], [0, max_val], 'r--', linewidth=2, label='100% Ocupación (Límite ideal)')

plt.fill_between([0, max_val], [0, max_val], max_val, color='red', alpha=0.05, label='Sobreocupación (Exceso de aforo)')
plt.fill_between([0, max_val], 0, [0, max_val], color='orange', alpha=0.05, label='Infrautilización (Espacio sobrante)')

plt.title('Análisis de Eficiencia de Asignación (Aforo vs Capacidad)', fontsize=14, pad=15)
plt.xlabel('Capacidad Física del Aula', fontsize=12)
plt.ylabel('Alumnos Asistentes (Matriculados)', fontsize=12)
plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
plt.tight_layout()
plt.savefig('2_eficiencia_asignacion.png', dpi=300)
plt.close()

# ==========================================
# GRÁFICO 3: Distribución de carga lectiva semanal
# ==========================================
plt.figure(figsize=(10, 6))
carga_semanal = df['dia'].value_counts().reindex(orden_dias).reset_index()
carga_semanal.columns = ['Dia', 'Num_Sesiones']

ax = sns.barplot(data=carga_semanal, x='Dia', y='Num_Sesiones', palette='viridis', hue='Dia', legend=False)
plt.title('Distribución de Carga Lectiva Semanal', fontsize=14, pad=15)
plt.xlabel('Día de la Semana', fontsize=12)
plt.ylabel('Número Total de Sesiones (Clases)', fontsize=12)

for i, v in enumerate(carga_semanal['Num_Sesiones']):
    ax.text(i, v + (v * 0.01), str(int(v)), color='black', ha='center', fontweight='bold')

plt.tight_layout()
plt.savefig('3_carga_lectiva_semanal.png', dpi=300)
plt.close()

print("¡Gráficos generados exitosamente en el directorio de trabajo!")