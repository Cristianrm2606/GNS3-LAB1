#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Laboratorio 1 - Inventario, Estado y Configuracion Segura con Python + SSH (Netmiko)
Curso: ITIEL-13 Redes Programables - UTN
Profesor: Randall Zamora Rojas

Que hace
--------
1. Lee el inventario de equipos desde inventario.yaml (R1), sin credenciales.
2. Pide las claves por variable de entorno LAB_PASS_<NOMBRE> o getpass (R2).
3. Se conecta por SSH con Netmiko dentro de un bloque `with`, maneja los errores
   por equipo (el script NO se detiene si uno falla) y guarda un session_log por
   equipo en logs/ (R3).
4. Recolecta el estado de cada equipo y lo convierte a diccionarios estructurados,
   con los comandos en un diccionario por device_type (R4).
5. Genera reporte_estado.json y una tabla resumen en consola (R5).
6. En los equipos con rol: escritura (MikroTik) asegura la interfaz lo-ssh-<N>
   (bridge sin puertos) con la IP 10.253.0.<N>/32, sin duplicar nada (R6).
7. Extra opcional: consulta el MikroTik tambien por su API REST y compara SSH vs REST.

Uso
---
  python lab1_inventario.py                 # recolecta estado y aplica el cambio (escritura)
  python lab1_inventario.py --estado        # solo lectura, no cambia nada
  python lab1_inventario.py --limpiar       # elimina SOLO los objetos lo-ssh-<N> propios
  python lab1_inventario.py -i inventario.yaml

Variables de entorno (R2)
-------------------------
  LAB_PASS_MT_LAB     clave del equipo mt-lab     (guiones -> _ y MAYUSCULAS)
  LAB_PASS_CISCO_LAB  clave del equipo cisco-lab

<N> es el numero de lista del estudiante (campo "estudiante" de inventario.yaml).
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from getpass import getpass
from pathlib import Path

import yaml
from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)

# ----------------------------------------------------------------------------
# Constantes (si cambia la red o la firma, se cambia solo aqui)
# ----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
INVENTARIO_DEFECTO = BASE_DIR / "inventario.yaml"
LOGS_DIR = BASE_DIR / "logs"
REPORTE_JSON = BASE_DIR / "reporte_estado.json"

ETIQUETA = "LAB1-ITIEL13"        # firma en los comentarios: --limpiar borra SOLO esto
PREFIJO_LO = "lo-ssh-"           # nombre del bridge: lo-ssh-<N>
IP_LO_BASE = "10.253.0"          # IP del bridge: 10.253.0.<N>/32
PREFIJO_VAR = "LAB_PASS_"        # variable de entorno de la clave

# Comandos de recoleccion por fabricante (R4). Agregar otro fabricante = agregar
# una entrada aqui, sin tocar el resto del codigo con if por equipo.
COMANDOS = {
    "mikrotik_routeros": {
        "nombre": "/system identity print",
        "uptime": "/system resource print",
        "interfaces": "/ip address print terse",
        "ruta": "/ip route print terse where dst-address=0.0.0.0/0",
    },
    "cisco_ios": {
        "nombre": "show running-config | include hostname",
        "uptime": "show version | include uptime",
        "interfaces": "show ip interface brief",
        "ruta": "show ip route 0.0.0.0",
    },
}


# ----------------------------------------------------------------------------
# R1 - Inventario
# ----------------------------------------------------------------------------
def cargar_inventario(ruta):
    """Carga inventario.yaml y valida los campos minimos de cada equipo."""
    with open(ruta, encoding="utf-8") as archivo:
        inventario = yaml.safe_load(archivo)

    equipos = inventario.get("equipos") or []
    if not equipos:
        raise SystemExit(f"[ERROR] No hay equipos en {ruta}")

    for equipo in equipos:
        faltantes = [c for c in ("nombre", "host", "device_type", "usuario", "rol")
                     if not equipo.get(c)]
        if faltantes:
            raise SystemExit(
                f"[ERROR] Equipo incompleto: {equipo.get('nombre', '?')} "
                f"(faltan: {', '.join(faltantes)})"
            )
        if equipo["device_type"] not in COMANDOS:
            raise SystemExit(
                f"[ERROR] device_type no soportado: {equipo['device_type']} "
                f"(soportados: {', '.join(COMANDOS)})"
            )
    return inventario


# ----------------------------------------------------------------------------
# R2 - Credenciales seguras
# ----------------------------------------------------------------------------
def clave(equipo_nombre):
    """Devuelve la clave desde LAB_PASS_<NOMBRE>; si no existe, la pide con getpass."""
    variable = (PREFIJO_VAR + re.sub(r"[^0-9A-Za-z]", "_", equipo_nombre)).upper()
    valor = os.getenv(variable)
    if valor:
        return valor
    return getpass(f"Contrasena para {equipo_nombre} ({variable}): ")


# ----------------------------------------------------------------------------
# R3 - Sesion Netmiko
# ----------------------------------------------------------------------------
def parametros_sesion(equipo, password):
    """Parametros de conexion Netmiko, con session_log por equipo (R3)."""
    return {
        "device_type": equipo["device_type"],
        "host": equipo["host"],
        "username": equipo["usuario"],
        "password": password,
        "secret": password,          # por si un equipo necesita modo privilegiado
        "fast_cli": False,
        "conn_timeout": 15,
        "session_log": str(LOGS_DIR / f"{equipo['nombre']}_session.log"),
    }


def recolectar(conn, device_type):
    """Ejecuta los comandos del device_type y devuelve las salidas crudas."""
    salidas = {}
    for clave_dato, comando in COMANDOS[device_type].items():
        salidas[clave_dato] = conn.send_command(comando, read_timeout=30)
    return salidas


# ----------------------------------------------------------------------------
# R4 - Estado estructurado (parsers por device_type)
# ----------------------------------------------------------------------------
def _campo(texto, campo):
    """Extrae 'campo: valor' de una salida de RouterOS."""
    m = re.search(rf"^\s*{re.escape(campo)}:\s*(.+)$", texto, re.MULTILINE)
    return m.group(1).strip() if m else None


def parsear_mikrotik(salidas):
    """Convierte las salidas de RouterOS a un diccionario estructurado."""
    interfaces = []
    for linea in salidas["interfaces"].splitlines():
        direccion = re.search(r"(?<![\w-])address=(\S+)", linea)
        interfaz = re.search(r"(?<![\w-])interface=(\S+)", linea)
        if direccion and interfaz:
            interfaces.append({"interfaz": interfaz.group(1), "ip": direccion.group(1)})

    gateway = None
    for linea in salidas["ruta"].splitlines():
        m = re.search(r"(?<![\w-])gateway=(\S+)", linea)
        if m:
            gateway = m.group(1)
            break

    return {
        "nombre": _campo(salidas["nombre"], "name"),
        "uptime": _campo(salidas["uptime"], "uptime"),
        "interfaces": interfaces,
        "gateway": gateway,
    }


def parsear_cisco(salidas):
    """Convierte las salidas de Cisco IOS a un diccionario estructurado."""
    m = re.search(r"hostname\s+(\S+)", salidas["nombre"])
    nombre = m.group(1) if m else None

    m = re.search(r"uptime is (.+)", salidas["uptime"])
    uptime = m.group(1).strip() if m else None

    interfaces = []
    for linea in salidas["interfaces"].splitlines()[1:]:  # salta el encabezado
        partes = linea.split()
        if len(partes) >= 2 and partes[0] != "Interface":
            ip = partes[1]
            if ip not in ("unassigned", "unassigned)"):
                interfaces.append({"interfaz": partes[0], "ip": ip})

    m = (re.search(r"Gateway of last resort is (\S+)", salidas["ruta"])
         or re.search(r"via (\S+)", salidas["ruta"]))
    gateway = m.group(1) if m else None

    return {
        "nombre": nombre,
        "uptime": uptime,
        "interfaces": interfaces,
        "gateway": gateway,
    }


PARSERS = {
    "mikrotik_routeros": parsear_mikrotik,
    "cisco_ios": parsear_cisco,
}


# ----------------------------------------------------------------------------
# R6 - Cambio de configuracion sin duplicados (solo rol: escritura)
# ----------------------------------------------------------------------------
def asegurar_lo_ssh(conn, n, nombre_estudiante, limpiar=False):
    """
    Asegura el bridge lo-ssh-<N> (sin puertos) con la IP 10.253.0.<N>/32.
    Patron: consultar -> si falta, crear -> verificar. Idempotente.
    Con limpiar=True elimina SOLO los objetos con la firma ETIQUETA.
    """
    bridge = f"{PREFIJO_LO}{n}"
    direccion = f"{IP_LO_BASE}.{n}/32"
    comentario = f"{ETIQUETA} N{n} {nombre_estudiante}".strip()

    salida_bridges = conn.send_command("/interface bridge print terse")
    salida_ips = conn.send_command("/ip address print terse")
    tiene_bridge = bridge in salida_bridges
    tiene_ip = direccion in salida_ips

    # --- Modo limpieza: borrar solo lo nuestro (firma ETIQUETA) ---
    if limpiar:
        if not tiene_bridge and not tiene_ip:
            return {"resultado": "sin cambios", "detalle": "no habia nada que limpiar"}
        comandos = []
        if tiene_ip:
            comandos.append(f'/ip address remove [find where comment~"{ETIQUETA}"]')
        if tiene_bridge:
            comandos.append(f'/interface bridge remove [find where comment~"{ETIQUETA}"]')
        conn.send_config_set(comandos)
        return {"resultado": "limpiado", "detalle": f"eliminados objetos de {ETIQUETA}"}

    # --- Modo asegurar: crear solo lo que falta ---
    cambios = []
    if not tiene_bridge:
        cambios.append(f'/interface bridge add name={bridge} comment="{comentario}"')
    if not tiene_ip:
        cambios.append(
            f'/ip address add address={direccion} interface={bridge} comment="{comentario}"'
        )

    if not cambios:
        return {"resultado": "sin cambios", "detalle": f"{bridge} ya existia"}

    conn.send_config_set(cambios)

    # Verificar con comandos de lectura despues del cambio
    verif_bridges = conn.send_command("/interface bridge print terse")
    verif_ips = conn.send_command("/ip address print terse")
    if bridge in verif_bridges and direccion in verif_ips:
        return {"resultado": "aplicado", "detalle": f"{bridge} con {direccion}"}
    return {"resultado": "error", "detalle": "no se pudo verificar el cambio"}


# ----------------------------------------------------------------------------
# Extra opcional - API REST del MikroTik (comparacion SSH vs REST)
# ----------------------------------------------------------------------------
def recolectar_rest(equipo, password):
    """Obtiene el estado del MikroTik por su API REST y lo devuelve estructurado."""
    try:
        import urllib3
        import requests
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception as error:  # requests no instalado
        return {"error": f"requests no disponible: {error}"}

    base = f"https://{equipo['host']}/rest"
    auth = (equipo["usuario"], password)
    try:
        identidad = requests.get(f"{base}/system/identity", auth=auth,
                                 verify=False, timeout=8).json()
        recurso = requests.get(f"{base}/system/resource", auth=auth,
                               verify=False, timeout=8).json()
        direcciones = requests.get(f"{base}/ip/address", auth=auth,
                                   verify=False, timeout=8).json()
        rutas = requests.get(f"{base}/ip/route", auth=auth,
                             verify=False, timeout=8).json()

        interfaces = [{"interfaz": a.get("interface"), "ip": a.get("address")}
                      for a in direcciones if a.get("address")]
        gateway = None
        for ruta in rutas:
            if ruta.get("dst-address") == "0.0.0.0/0":
                gateway = ruta.get("gateway")
                break
        return {
            "nombre": identidad.get("name"),
            "uptime": recurso.get("uptime"),
            "interfaces": interfaces,
            "gateway": gateway,
        }
    except Exception as error:
        return {"error": f"{type(error).__name__}: {error}"}


def comparar_ssh_rest(datos_ssh, datos_rest):
    """Compara los datos de SSH contra REST (True/False)."""
    if not datos_rest or datos_rest.get("error"):
        return None
    return {
        "nombre": datos_ssh.get("nombre") == datos_rest.get("nombre"),
        "gateway": datos_ssh.get("gateway") == datos_rest.get("gateway"),
        "interfaces": len(datos_ssh.get("interfaces", [])) == len(datos_rest.get("interfaces", [])),
    }


# ----------------------------------------------------------------------------
# Procesamiento por equipo
# ----------------------------------------------------------------------------
def procesar_equipo(equipo, n, nombre_estudiante, args):
    """Procesa un equipo y devuelve su registro para el reporte."""
    registro = {
        "nombre": equipo["nombre"],
        "host": equipo["host"],
        "device_type": equipo["device_type"],
        "rol": equipo["rol"],
        "estado": "ok",
        "error": None,
        "datos": None,
        "cambio": None,
        "rest": None,
        "rest_coincide": None,
    }

    try:
        password = clave(equipo["nombre"])
        with ConnectHandler(**parametros_sesion(equipo, password)) as conn:
            salidas = recolectar(conn, equipo["device_type"])
            registro["datos"] = PARSERS[equipo["device_type"]](salidas)

            # R6: cambio solo en equipos de escritura
            if equipo["rol"] == "escritura" and equipo["device_type"] == "mikrotik_routeros":
                if args.limpiar:
                    registro["cambio"] = asegurar_lo_ssh(conn, n, nombre_estudiante, limpiar=True)
                elif args.estado:
                    registro["cambio"] = {"resultado": "sin cambios",
                                          "detalle": "modo --estado (no aplica)"}
                else:
                    registro["cambio"] = asegurar_lo_ssh(conn, n, nombre_estudiante)

            # Extra REST (solo MikroTik)
            if equipo["device_type"] == "mikrotik_routeros":
                datos_rest = recolectar_rest(equipo, password)
                registro["rest"] = datos_rest
                registro["rest_coincide"] = comparar_ssh_rest(registro["datos"], datos_rest)

    except NetmikoAuthenticationException as error:
        registro["estado"] = "error"
        registro["error"] = f"Autenticacion: {error}"
    except NetmikoTimeoutException as error:
        registro["estado"] = "error"
        registro["error"] = f"Timeout: {error}"
    except Exception as error:
        registro["estado"] = "error"
        registro["error"] = f"{type(error).__name__}: {error}"

    return registro


# ----------------------------------------------------------------------------
# R5 - Reporte JSON y tabla en consola
# ----------------------------------------------------------------------------
def escribir_reporte(resultados, n):
    """Guarda reporte_estado.json con fecha/hora y el estado de cada equipo."""
    reporte = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "estudiante": n,
        "etiqueta": ETIQUETA,
        "equipos": resultados,
    }
    with open(REPORTE_JSON, "w", encoding="utf-8") as archivo:
        json.dump(reporte, archivo, indent=2, ensure_ascii=False)
    return reporte


def imprimir_tabla(resultados):
    """Resumen en consola: equipo, IP, estado, cantidad de interfaces, gateway."""
    encabezado = f"{'EQUIPO':<12} {'IP':<15} {'ESTADO':<8} {'IFACES':>6} {'GATEWAY':<16}"
    print()
    print(encabezado)
    print("-" * len(encabezado))
    for registro in resultados:
        datos = registro.get("datos") or {}
        cantidad = len(datos.get("interfaces", [])) if datos else 0
        gateway = (datos.get("gateway") if datos else None) or "-"
        print(f"{registro['nombre']:<12} {registro['host']:<15} "
              f"{registro['estado']:<8} {cantidad:>6} {gateway:<16}")

    # Detalle de errores y cambios
    for registro in resultados:
        if registro["estado"] != "ok" and registro.get("error"):
            print(f"  [!] {registro['nombre']}: {registro['error']}")
        cambio = registro.get("cambio")
        if cambio:
            print(f"  [lo-ssh] {registro['nombre']}: "
                  f"{cambio['resultado']} - {cambio.get('detalle', '')}")
        if registro.get("rest_coincide") is not None:
            print(f"  [REST]   {registro['nombre']}: SSH vs REST -> {registro['rest_coincide']}")


# ----------------------------------------------------------------------------
# CLI / main
# ----------------------------------------------------------------------------
def parsear_argumentos():
    parser = argparse.ArgumentParser(
        description="Lab 1 - Inventario, estado y configuracion segura (Netmiko)."
    )
    parser.add_argument("-i", "--inventario", default=str(INVENTARIO_DEFECTO),
                        help="Ruta del inventario YAML (por defecto: inventario.yaml).")
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument("--estado", action="store_true",
                      help="Solo lectura: recolecta el estado sin aplicar cambios.")
    modo.add_argument("--limpiar", action="store_true",
                      help="Elimina SOLO los objetos lo-ssh-<N> con la firma propia.")
    return parser.parse_args()


def main():
    args = parsear_argumentos()
    inventario = cargar_inventario(args.inventario)

    n = inventario.get("estudiante")
    if n is None:
        raise SystemExit("[ERROR] Falta el campo 'estudiante' (numero de lista N) en el YAML.")
    nombre_estudiante = inventario.get("estudiante_nombre", "")
    equipos = inventario["equipos"]

    LOGS_DIR.mkdir(exist_ok=True)

    print(f"Inventario: {args.inventario}")
    print(f"Estudiante N={n} ({nombre_estudiante}) | equipos: {len(equipos)}")

    resultados = [procesar_equipo(equipo, n, nombre_estudiante, args) for equipo in equipos]

    escribir_reporte(resultados, n)
    print(f"Reporte escrito en: {REPORTE_JSON}")
    print(f"Logs de sesion en: {LOGS_DIR}")
    imprimir_tabla(resultados)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nInterrumpido por el usuario.")
