# Lab 1 - Inventario, Estado y Configuracion Segura con Python + SSH (Netmiko)

**Curso:** ITIEL-13 Redes Programables - UTN  
**Profesor:** Randall Zamora Rojas  
**Estudiante:** Cristian Rojas Morales - N `<CAMBIAR>`  
**Periodo:** III - 2026

Script que lee un inventario YAML, se conecta por SSH (Netmiko) a los equipos del
laboratorio GNS3, recolecta su estado como datos estructurados, genera
`reporte_estado.json` y aplica de forma idempotente el cambio de la interfaz
`lo-ssh-<N>` en el MikroTik.

## Requisitos

- Python 3.9 o superior.
- Acceso al laboratorio GNS3 por Tailscale (red `10.60.30.0/24`).
- Git (opcional, para el repositorio).

## Instalacion

```bash
python -m venv env
# Windows PowerShell:
.\env\Scripts\Activate.ps1
# Linux / macOS:
source env/bin/activate

pip install -r requirements.txt
```

## Variables de entorno (credenciales)

Ninguna contrasena vive en el codigo ni en el YAML. El script toma la clave de la
variable `LAB_PASS_<NOMBRE>` (nombre en mayusculas y guiones como `_`); si no
existe, la pide con `getpass`.

```bash
# Windows PowerShell
$env:LAB_PASS_MT_LAB = "clave-del-mikrotik"
$env:LAB_PASS_CISCO_LAB = "clave-del-cisco"

# Linux / macOS
export LAB_PASS_MT_LAB="clave-del-mikrotik"
export LAB_PASS_CISCO_LAB="clave-del-cisco"
```

Prueba del manejo de errores: exporta una clave incorrecta y corre el script; el
equipo afectado se reporta como error y el script continua con los demas.

## Ejecucion

```bash
python lab1_inventario.py              # recolecta estado y aplica el cambio (rol escritura)
python lab1_inventario.py --estado     # solo lectura: no cambia nada
python lab1_inventario.py --limpiar    # elimina SOLO los objetos lo-ssh-<N> propios
python lab1_inventario.py -i inventario.yaml
```

Idempotencia (R6): ejecutar dos veces seguidas. La segunda debe reportar
`sin cambios` para `lo-ssh-<N>`.

Antes de ejecutar, edita en `inventario.yaml`:

- `estudiante: <N>` -> tu numero de lista.
- `estudiante_nombre` -> tu nombre (va en el comentario de los objetos creados).
- `usuario` -> debe coincidir con `laboratorio_1/inventario_ejemplo.yaml`.

## Estructura del repositorio

```
lab1-<carne>/
├── README.md              # este archivo (incluye la declaracion de uso de IA)
├── requirements.txt       # netmiko, PyYAML, requests
├── .gitignore             # env/, __pycache__/, logs con datos sensibles
├── inventario.yaml        # SIN contrasenas
├── lab1_inventario.py     # script principal
├── reporte_estado.json    # salida de una ejecucion real
└── logs/                  # session_log de cada equipo
```

## Correspondencia con los requerimientos

| Req. | Donde esta |
|------|------------|
| R1. Inventario YAML externo | `inventario.yaml` + `cargar_inventario()` |
| R2. Credenciales seguras | `clave()` (env `LAB_PASS_<NOMBRE>` o `getpass`) |
| R3. Conexion robusta | `parametros_sesion()`, `procesar_equipo()` (`with ConnectHandler`, excepciones por equipo, `session_log` en `logs/`) |
| R4. Estado estructurado | `COMANDOS` (por `device_type`) + `parsear_mikrotik()` / `parsear_cisco()` |
| R5. Reporte | `escribir_reporte()` (`reporte_estado.json`) + `imprimir_tabla()` |
| R6. Cambio sin duplicados | `asegurar_lo_ssh()` (consultar -> crear si falta -> verificar; `--limpiar`) |
| Extra REST | `recolectar_rest()` + `comparar_ssh_rest()` |
| Extra multivendor | entrada `cisco_ios` en el inventario y en `COMANDOS`/`PARSERS` |

Los comandos por fabricante viven en el diccionario `COMANDOS` y sus parsers en
`PARSERS`: agregar otro fabricante es agregar una entrada, sin `if` por equipo.

## Topologia (GNS3)

```
Cloud (Internet 10.60.30.0/24, gw .1)
  └── SW1
        ├── MikroTik 10.60.30.202 (ether1)  -> PC2 (VPCS)
        └── Cisco IOS 3725 10.60.30.203 (Fa0/0) -> PC1 (VPCS)
```

## Declaracion de uso de IA

Se utilizo un asistente de IA (opencode, modelo big-pickle) como apoyo para:
redactar la estructura inicial del script, el inventario y este README, y para
revisar el manejo de errores y la logica de idempotencia de `lo-ssh-<N>`.

El estudiante reviso, comprendio y probo todo el codigo, y es responsable de su
funcionamiento y de poder explicarlo en la defensa oral.
