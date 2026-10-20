# Lab 1 - Inventario, Estado y Configuracion Segura con Python + SSH (Netmiko)

**Curso:** ITIEL-13 Redes Programables - UTN  
**Profesor:** Randall Zamora Rojas  
**Estudiante:** Cristian Rojas Morales - Carne 208850384 - N `26`  
**Periodo:** III - 2026

Script que lee un inventario YAML, se conecta por SSH (Netmiko) a los equipos del
laboratorio GNS3, recolecta su estado como datos estructurados, genera
`reporte_estado.json` y aplica de forma idempotente el cambio de la interfaz
`lo-ssh-26` (IP `10.253.0.26/32`) en el MikroTik.

## Requisitos

- Python 3.9 o superior (probado con Python 3.13 en Debian 13).
- Acceso a la red del laboratorio `10.60.30.0/24` (laboratorio GNS3 del curso por
  Tailscale, o la replica local descrita abajo).
- Git.

## Instalacion

```bash
python3 -m venv env
source env/bin/activate          # Windows PowerShell: .\env\Scripts\Activate.ps1
pip install -r requirements.txt
```

`paramiko` queda fijado en `<4`: es la version probada contra el SSH antiguo del
Cisco IOS 12.4 (`SSH-2.0-Cisco-1.25`).

## Variables de entorno (credenciales)

Ninguna contrasena vive en el codigo, en el YAML ni en el repositorio. El script toma
la clave de la variable `LAB_PASS_<NOMBRE>` (nombre del equipo en mayusculas, guiones
como `_`); si no existe, la pide con `getpass`.

```bash
export LAB_PASS_MT_LAB="clave-del-mikrotik"     # equipo mt-lab
export LAB_PASS_CISCO_LAB="clave-del-cisco"     # equipo cisco-lab
```

Prueba del manejo de errores (R3): exportar una clave incorrecta y correr el script.
El equipo afectado se reporta como `error` y el script continua con los demas:

```bash
LAB_PASS_CISCO_LAB=mala python lab1_inventario.py --estado
```

## Ejecucion

```bash
python lab1_inventario.py              # recolecta estado y asegura lo-ssh-26 (rol escritura)
python lab1_inventario.py              # 2.a vez: debe decir "sin cambios"
python lab1_inventario.py --estado     # solo lectura: no cambia nada
python lab1_inventario.py --limpiar    # elimina SOLO lo-ssh-26 y 10.253.0.26/32
python lab1_inventario.py -i otro_inventario.yaml
```

Salidas: tabla en consola, `reporte_estado.json` y `logs/<equipo>_session.log`.

## Estructura del repositorio

```
lab1-208850384/
├── README.md              # este archivo (incluye la declaracion de uso de IA)
├── requirements.txt       # netmiko, paramiko<4, PyYAML, requests
├── .gitignore             # env/, __pycache__/, archivos locales
├── inventario.yaml        # SIN contrasenas
├── lab1_inventario.py     # script principal
├── reporte_estado.json    # salida de una ejecucion real
└── logs/                  # session_log de cada equipo
```

## Correspondencia con los requerimientos

| Req. | Donde esta |
|------|------------|
| R1. Inventario YAML externo | `inventario.yaml` + `cargar_inventario()` (valida campos minimos y `device_type`) |
| R2. Credenciales seguras | `clave()` (env `LAB_PASS_<NOMBRE>` o `getpass`) |
| R3. Conexion robusta | `parametros_sesion()`, `procesar_equipo()` (`with ConnectHandler`, excepciones por equipo, `session_log` en `logs/`) |
| R4. Estado estructurado | `COMANDOS` (por `device_type`) + `PARSERS` (`parsear_mikrotik()` / `parsear_cisco()`) |
| R5. Reporte | `escribir_reporte()` (`reporte_estado.json`) + `imprimir_tabla()` |
| R6. Cambio sin duplicados | `asegurar_lo_ssh()`: consultar -> crear solo lo que falta -> verificar; `--limpiar` |
| Extra REST | `recolectar_rest()` + `comparar_ssh_rest()` (se consulta antes del cambio, mismo estado que SSH) |
| Extra multivendor | entrada `cisco_ios` en el inventario y en `COMANDOS`/`PARSERS` |

Los comandos por fabricante viven en `COMANDOS` y sus parsers en `PARSERS`: agregar
otro fabricante es agregar una entrada, sin `if` por equipo.

### Como evita tocar objetos ajenos (R6)

- Busca por valor exacto: `print terse where name="lo-ssh-26"` y una expresion regular
  que exige el nombre completo, para que `lo-ssh-2` no coincida con `lo-ssh-26`.
- Todo lo que crea lleva el comentario `LAB1-ITIEL13 N26 <nombre>`.
- `--limpiar` borra solo si coinciden **el nombre/IP propios y la firma con el N**
  (`comment~"^LAB1-ITIEL13 N26 "`). Nunca borra por la etiqueta sola, que podrian
  compartir otros estudiantes.

## Topologia (GNS3)

```
Internet (10.60.30.0/24, gw .1)
  └── SW1
        ├── MikroTik RouterOS v7  10.60.30.202 (ether1) -- ether2 192.168.20.1/24 -- PC2 (VPCS)
        └── Cisco IOS 3725        10.60.30.203 (Fa0/0)  -- Fa0/1 172.16.10.1/24  -- PC1 (VPCS)
```

### Ejecucion real incluida en el repositorio

El `reporte_estado.json` y los `logs/` de este repositorio salen de una ejecucion
real contra una **replica local** de la topologia del enunciado, montada en GNS3
2.2.61 sobre Debian 13: mismas IP (`10.60.30.202`/`.203`), mismos `device_type`,
usuario `lab-ssh`, y Debian como gateway `10.60.30.1`. Por eso el mismo
`inventario.yaml` funciona sin cambios contra el laboratorio compartido del curso:
solo cambian las claves de las variables de entorno.

## Declaracion de uso de IA

Se usaron asistentes de IA como apoyo:

- **opencode (modelo big-pickle):** estructura inicial del script, del inventario y
  de este README.
- **Claude Code (Anthropic):** preparar el entorno (Debian, GNS3 y la replica local
  de la topologia); revisar el script y corregir errores: `--limpiar` borraba por la
  etiqueta comun (podia eliminar objetos de otros estudiantes), la busqueda de
  `lo-ssh-<N>` por subcadena, el parser del gateway del Cisco, el orden de la
  consulta REST frente al cambio, y el `.gitignore` que excluia `logs/`.

El estudiante reviso, comprendio y probo todo el codigo, y es responsable de su
funcionamiento y de poder explicarlo en la defensa oral.
