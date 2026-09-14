"""Panel para encender y apagar el flujo diario, con botones.

Se abre con doble clic (ver `Flujo diario.bat`) y responde a la pregunta que
importa de un vistazo: **¿esto va a correr manana, y va a escribir?**

Por que un panel y no un acceso directo que alterna: el modo de fallo peligroso
aqui no es que cueste apagarlo, es **creer que esta apagado cuando esta
encendido** -- o al reves. Un boton que alterna a ciegas no lo evita; mostrar el
estado si. De ahi que la mitad de la ventana sea el estado y no los botones.

Usa tkinter, que viene con Python: no anade ninguna dependencia.

    python scripts\\panel.py
"""

from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from moodle_sinu.tarea_programada import (  # noqa: E402
    NOMBRE_TAREA,
    apagar,
    leer_estado,
)

PY = RAIZ / ".venv" / "Scripts" / "python.exe"

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

VERDE = "#1E8E3E"
ROJO = "#D93025"
GRIS = "#5F6368"
AMBAR = "#B06000"


def _cuando(momento) -> str:
    if momento is None:
        return "no volverá a ejecutarse"
    return f"{DIAS[momento.weekday()]} {momento:%d/%m/%Y} a las {momento:%H:%M}"


class Panel:
    def __init__(self, raiz: tk.Tk) -> None:
        self.raiz = raiz
        raiz.title("Flujo diario Moodle-SINU")
        raiz.resizable(False, False)

        marco = ttk.Frame(raiz, padding=18)
        marco.grid(sticky="nsew")

        self.lbl_estado = ttk.Label(marco, font=("Segoe UI", 15, "bold"))
        self.lbl_estado.grid(row=0, column=0, columnspan=3, sticky="w")

        self.lbl_proxima = ttk.Label(marco, font=("Segoe UI", 10))
        self.lbl_proxima.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        self.lbl_modo = ttk.Label(marco, font=("Segoe UI", 10))
        self.lbl_modo.grid(row=2, column=0, columnspan=3, sticky="w", pady=(2, 14))

        ttk.Separator(marco).grid(row=3, column=0, columnspan=3, sticky="ew")

        ttk.Label(marco, text="Programación:", font=("Segoe UI", 10, "bold")).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(12, 6)
        )

        ttk.Button(
            marco, text="Todos los días (L-V)", width=22, command=self.diario
        ).grid(row=5, column=0, padx=(0, 6))
        ttk.Button(marco, text="Solo mañana", width=16, command=self.una_vez).grid(
            row=5, column=1, padx=(0, 6)
        )
        self.btn_apagar = ttk.Button(
            marco, text="Apagar", width=12, command=self.apagar
        )
        self.btn_apagar.grid(row=5, column=2)

        self.lbl_aviso = ttk.Label(
            marco, font=("Segoe UI", 9), foreground=GRIS, wraplength=430, justify="left"
        )
        self.lbl_aviso.grid(row=6, column=0, columnspan=3, sticky="w", pady=(14, 0))

        ttk.Button(marco, text="Actualizar", width=12, command=self.refrescar).grid(
            row=7, column=0, sticky="w", pady=(12, 0)
        )

        self.refrescar()

    # --- estado -----------------------------------------------------------

    def refrescar(self) -> None:
        e = leer_estado()
        self.lbl_estado.config(
            text=e.resumen(),
            foreground=VERDE if e.encendida else (GRIS if e.existe else ROJO),
        )
        self.lbl_proxima.config(
            text=f"Próxima ejecución: {_cuando(e.proxima)}"
            if e.encendida
            else "No hay ninguna ejecución programada."
        )
        # El modo se muestra SIEMPRE y en ambar cuando escribe: es la diferencia
        # entre un ensayo y tocar matriculas de verdad, y no debe haber que
        # recordarla de memoria.
        if not e.existe:
            self.lbl_modo.config(text="")
        elif e.escribe:
            self.lbl_modo.config(
                text="Modo REAL: modificará matrículas en SINU.", foreground=AMBAR
            )
        else:
            self.lbl_modo.config(
                text="Modo simulación: recorre todo y no escribe.", foreground=GRIS
            )
        self.btn_apagar.config(state="normal" if e.encendida else "disabled")
        self.lbl_aviso.config(
            text=(
                "El equipo tiene que estar encendido y con su sesión iniciada a "
                "esa hora: el flujo abre Chrome con ventana porque la subida a "
                "Drive no funciona sin escritorio."
            )
        )

    # --- acciones ---------------------------------------------------------

    def _programar(self, una_vez: bool) -> None:
        orden = [str(PY), "scripts/programar_9am.py"]
        if una_vez:
            orden.append("--una-vez")
        r = subprocess.run(
            orden, cwd=str(RAIZ), capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        if r.returncode != 0:
            messagebox.showerror(
                "No se pudo programar", (r.stderr or r.stdout)[-700:]
            )
        self.refrescar()

    def diario(self) -> None:
        self._programar(una_vez=False)

    def una_vez(self) -> None:
        self._programar(una_vez=True)

    def apagar(self) -> None:
        if not messagebox.askyesno(
            "Apagar el flujo diario",
            "El flujo dejará de ejecutarse solo.\n\n"
            "Las matrículas del día habrá que procesarlas a mano:\n"
            "  python scripts\\dia_completo.py --ejecutar-de-verdad\n\n"
            "¿Apagar?",
        ):
            return
        bien, detalle = apagar(NOMBRE_TAREA)
        if not bien:
            messagebox.showerror("No se pudo apagar", detalle or "schtasks fallo.")
        self.refrescar()


def main() -> int:
    if not PY.is_file():
        print(f"No existe {PY}. Rehacer el entorno (ver README).")
        return 1
    raiz = tk.Tk()
    try:
        raiz.call("tk", "scaling", 1.3)
    except tk.TclError:
        pass
    Panel(raiz)
    raiz.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
