import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

# Configuración visual general
sns.set_theme(style="whitegrid")
plt.rcParams['figure.figsize'] = (14, 20)

# ==========================================
# 1. GENERACIÓN DE DATOS (MOCK DATA)
# Sustituye este bloque por la lectura de tu dataset real.
# Ejemplo: df = pd.read_csv('horarios.csv')
# ==========================================
dias_semana = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes']
franjas_horarias = [f"{h:02d}:00" for h in range(8, 22)]

np.random.seed(42) # Para reproducibilidad
datos_simulados = []

for dia in dias_semana:
    for franja in franjas_horarias:
        # Simulamos picos de demanda por la mañana para forzar el desbordamiento
        if "09:00" <= franja <= "13:00":
            demanda = np.random.randint(15, 24)
        else:
            demanda = np.random.randint(5, 18)
        datos_simulados.append({'Dia': dia, 'Franja': franja, 'Demanda': demanda})

df = pd.DataFrame(datos_simulados)
# df debe tener columnas: ['Dia', 'Franja', 'Demanda'] para que el código funcione

# ==========================================
# 2. PARÁMETROS DEL RETO (REGLA 8)
# ==========================================
TOTAL_AULAS_DOCENTES = 21
AULAS_RESERVA_R8 = 2
UMBRAL_OFERTA = TOTAL_AULAS_DOCENTES - AULAS_RESERVA_R8  # 19 aulas

# ==========================================
# 3. VISUALIZACIÓN
# ==========================================
fig, axes = plt.subplots(nrows=5, ncols=1, sharex=True, sharey=True)
fig.suptitle('Demanda de Aulas vs Oferta Disponible (Validación Regla 8)', fontsize=20, y=0.97)

for i, dia in enumerate(dias_semana):
    ax = axes[i]
    df_dia = df[df['Dia'] == dia].copy()
    
    # Lógica de colores: Rojo si la demanda supera la oferta disponible, Azul oscuro si está bajo control
    colores = ['#d63031' if d > UMBRAL_OFERTA else '#0984e3' for d in df_dia['Demanda']]
    
    # Crear el gráfico de barras
    bars = ax.bar(df_dia['Franja'], df_dia['Demanda'], color=colores, edgecolor='black', alpha=0.85)
    
    # Dibujar la línea de umbral normativo (Oferta real)
    ax.axhline(y=UMBRAL_OFERTA, color='#2d3436', linestyle='--', linewidth=2.5, 
               label=f'Límite Operativo ({UMBRAL_OFERTA} aulas)')
    
    # Personalización del Subplot
    ax.set_title(f"{dia}", fontsize=14, fontweight='bold', loc='left')
    ax.set_ylabel('Aulas Necesarias', fontsize=11)
    
    # Añadir las etiquetas numéricas encima de cada barra para lectura exacta
    for bar in bars:
        yval = bar.get_height()
        # Resaltar en negrita si supera el umbral
        weight = 'bold' if yval > UMBRAL_OFERTA else 'normal'
        ax.text(bar.get_x() + bar.get_width()/2, yval + 0.5, int(yval), 
                ha='center', va='bottom', fontsize=10, fontweight=weight)
    
    # Mostrar la leyenda solo en el primer gráfico para no saturar
    if i == 0:
        ax.legend(loc='upper right', frameon=True, fontsize=12)

# Ajustes finales de formato
plt.xlabel('Franja Horaria (Inicio de la sesión)', fontsize=14)
plt.xticks(rotation=45, ha='right', fontsize=11)
plt.yticks(fontsize=11)

# Ajustar el espaciado para que no se superpongan los títulos
plt.tight_layout()
plt.subplots_adjust(top=0.92, hspace=0.3)

# Guardar y mostrar
plt.savefig('validacion_aulas_r8.png', dpi=300, bbox_inches='tight')
plt.show()