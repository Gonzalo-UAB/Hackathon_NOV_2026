import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

# Configuración visual general
sns.set_theme(style="whitegrid")
plt.rcParams['figure.figsize'] = (14, 18)

# ==========================================
# 1. LECTURA Y PREPROCESADO DE TUS DATOS
# ==========================================
sessions = pd.read_csv('sessions.csv')
proposta = pd.read_csv('proposta_partida.csv')
aules = pd.read_csv('aules.csv')

# Unir proposta_partida con sessions para asociar las fechas de las clases
full_df = pd.merge(
    proposta[['id_sessio', 'dia', 'h_ini', 'aula']],
    sessions[['id_sessio', 'data']],
    on='id_sessio',
    how='inner',
)

# Filtrar únicamente las clases que tienen aula asignada
full_df = full_df[full_df['aula'].notna() & (full_df['aula'] != '')]

# Agrupar por día, hora de inicio y fecha para contar aulas simultáneas ocupadas
demanda_por_fecha = (
    full_df.groupby(['dia', 'h_ini', 'data'])['aula']
    .nunique()
    .reset_index(name='Demanda')
)

# Obtener la demanda máxima simultánea para cada franja por día de la semana
demanda_max = (
    demanda_por_fecha.groupby(['dia', 'h_ini'])['Demanda'].max().reset_index()
)

# Mapeo de códigos de días a nombres en español
dias_orden = ['L', 'M', 'X', 'J', 'V']
dias_nombres = {
    'L': 'Lunes',
    'M': 'Martes',
    'X': 'Miércoles',
    'J': 'Jueves',
    'V': 'Viernes',
}

# ==========================================
# 2. PARÁMETROS DEL RETO (REGLA 8 DINO-ADAPTADOS)
# ==========================================
# Calculamos las aulas ordinarias directamente desde aules.csv
if 'ordinaria' in aules.columns:
  TOTAL_AULAS_DOCENTES = int(aules['ordinaria'].sum())
else:
  TOTAL_AULAS_DOCENTES = len(aules)

AULAS_RESERVA_R8 = 2
UMBRAL_OFERTA = TOTAL_AULAS_DOCENTES - AULAS_RESERVA_R8  # Ej: 21 - 2 = 19

# ==========================================
# 3. VISUALIZACIÓN
# ==========================================
fig, axes = plt.subplots(nrows=5, ncols=1, sharex=False, sharey=True)
fig.suptitle(
    'Demanda de Aulas vs Oferta Disponible (Validación Regla 8)',
    fontsize=18,
    y=0.98,
)

for i, dia_code in enumerate(dias_orden):
  ax = axes[i]
  df_dia = (
      demanda_max[demanda_max['dia'] == dia_code].sort_values('h_ini').copy()
  )

  # Rojo si supera la oferta disponible (19), azul si está dentro del umbral
  colores = [
      '#d63031' if d > UMBRAL_OFERTA else '#0984e3' for d in df_dia['Demanda']
  ]

  # Crear gráfico de barras
  bars = ax.bar(
      df_dia['h_ini'],
      df_dia['Demanda'],
      color=colores,
      edgecolor='black',
      alpha=0.85,
  )

  # Línea de umbral normativo (Oferta real disponible)
  ax.axhline(
      y=UMBRAL_OFERTA,
      color='#2d3436',
      linestyle='--',
      linewidth=2.5,
      label=f'Límite Operativo ({UMBRAL_OFERTA} aulas)',
  )

  # Personalización
  ax.set_title(
      f'{dias_nombres[dia_code]}', fontsize=13, fontweight='bold', loc='left'
  )
  ax.set_ylabel('Aulas Necesarias', fontsize=11)

  # Etiquetas con los valores encima de las barras
  for bar in bars:
    yval = bar.get_height()
    weight = 'bold' if yval > UMBRAL_OFERTA else 'normal'
    ax.text(
        bar.get_x() + bar.get_width() / 2,
        yval + 0.5,
        int(yval),
        ha='center',
        va='bottom',
        fontsize=9,
        fontweight=weight,
    )

  if i == 0:
    ax.legend(loc='upper right', frameon=True, fontsize=11)

# Ajustes finales de formato
plt.xlabel('Franja Horaria (Inicio de la sesión)', fontsize=13)
plt.tight_layout()
plt.subplots_adjust(top=0.94, hspace=0.35)

# Guardar y mostrar
plt.savefig('validacion_aulas_r8.png', dpi=300, bbox_inches='tight')
plt.show()