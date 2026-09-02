"""Captura de las interacciones del operador, con el DOM de cada elemento tocado.

Por que existe, y por que no basta el grabador de Playwright
------------------------------------------------------------
El grabador (`enableRecorder` con `outputFile`) vuelca el archivo al cerrar el
navegador de forma ordenada. El 01/09/2026 la sesion acabo con la ventana
cerrada a mano y **no se escribio nada**: se perdio el trabajo manual del
operador entero. Repetir una pasada de 15 matriculas reales por un buffer
perdido no es aceptable.

Esto lo resuelve por otra via: se inyecta un oyente en la pagina que, en cada
clic o cambio, publica por `console.log` una descripcion del elemento tocado.
Python escucha esos mensajes y los escribe en un JSONL **en el momento**. Si el
navegador muere, lo capturado hasta ese instante ya esta en disco.

Y captura algo que el grabador no da: no solo un selector que "funciona hoy",
sino los atributos con los que decidir cual es ESTABLE. En SmartClient eso es lo
unico que importa -- los ids (`isc_7O`) se regeneran en cada carga, asi que un
selector por id esta roto antes de escribirse.

Que se anota de cada interaccion
--------------------------------
- Que pestana (URL y titulo): el operador alterna entre el Sheet y SINU, y saber
  donde ocurrio cada cosa es parte del dato.
- El elemento: etiqueta, rol, aria-label, name, id, clases, tipo, si es un
  check y como expone su estado, y su texto.
- Su cadena de ancestros, para poder anclar por contenedor cuando el propio
  elemento no tiene nada estable.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from playwright.sync_api import BrowserContext, Page

log = logging.getLogger(__name__)

#: Prefijo con el que el oyente marca sus mensajes, para no confundirlos con los
#: cientos de logs que SmartClient escribe por su cuenta.
MARCA = "@@CAPTURA@@"

#: Eventos que se escuchan. `change` es imprescindible: es el que delata un
#: checkbox, y en SmartClient el clic puede caer en un div decorativo mientras
#: el estado real cambia en otro elemento.
EVENTOS = ("click", "change", "input")

_GUION = """
() => {
  if (window.__capturaPuesta) return;
  window.__capturaPuesta = true;

  const desc = (e) => {
    if (!e || !e.tagName) return null;
    const at = {};
    for (const a of ['role','aria-label','aria-checked','name','type','title',
                     'data-testid','checked','value']) {
      const v = e.getAttribute ? e.getAttribute(a) : null;
      if (v !== null && v !== undefined) at[a] = String(v).slice(0, 60);
    }
    if (e.checked !== undefined) at['prop.checked'] = e.checked;
    return {
      tag: e.tagName,
      id: e.id || null,
      clases: (e.className && e.className.toString
               ? e.className.toString() : '').slice(0, 90),
      texto: (e.innerText || e.textContent || '').replace(/\\s+/g, ' ')
             .trim().slice(0, 70),
      attrs: at,
    };
  };

  const ancestros = (e) => {
    const salida = [];
    let n = e.parentElement;
    for (let i = 0; i < 6 && n; i++) {
      salida.push({
        tag: n.tagName,
        id: n.id || null,
        clases: (n.className && n.className.toString
                 ? n.className.toString() : '').slice(0, 70),
        role: n.getAttribute ? n.getAttribute('role') : null,
      });
      n = n.parentElement;
    }
    return salida;
  };

  const manejar = (ev) => {
    try {
      const o = ev.target;
      if (!o || !o.tagName) return;
      const carga = {
        evento: ev.type,
        objetivo: desc(o),
        ancestros: ancestros(o),
      };
      console.log('%(marca)s' + JSON.stringify(carga));
    } catch (err) { /* nunca romper la pagina del operador */ }
  };

  for (const tipo of %(eventos)s) {
    document.addEventListener(tipo, manejar, true);
  }
}
""".replace("%(marca)s", MARCA).replace("%(eventos)s", json.dumps(list(EVENTOS)))


class Capturador:
    """Escribe en JSONL cada interaccion, en el momento en que ocurre."""

    def __init__(self, destino: Path):
        self.destino = Path(destino)
        self.destino.parent.mkdir(parents=True, exist_ok=True)
        self.n = 0
        # Se abre en modo linea a linea y se hace flush en cada apunte: el punto
        # de todo esto es que lo capturado sobreviva a que el proceso muera.
        self._fh = self.destino.open("a", encoding="utf-8")

    def _apuntar(self, registro: dict) -> None:
        registro["momento"] = datetime.now().isoformat(timespec="seconds")
        registro["n"] = self.n
        self._fh.write(json.dumps(registro, ensure_ascii=False) + "\n")
        self._fh.flush()

    def _al_mensaje(self, pagina: Page, mensaje) -> None:
        texto = mensaje.text or ""
        if not texto.startswith(MARCA):
            return
        try:
            carga = json.loads(texto[len(MARCA) :])
        except ValueError:
            return
        self.n += 1
        try:
            carga["pestana_url"] = pagina.url[:120]
            carga["pestana_titulo"] = (pagina.title() or "")[:70]
        except Exception:  # noqa: BLE001 - la pagina puede estar navegando
            carga["pestana_url"] = "(ilegible)"
            carga["pestana_titulo"] = "(ilegible)"
        self._apuntar(carga)
        obj = carga.get("objetivo") or {}
        log.info(
            "[%d] %s en <%s> %r (%s)",
            self.n,
            carga.get("evento"),
            obj.get("tag"),
            (obj.get("texto") or "")[:30],
            carga.get("pestana_titulo", "")[:28],
        )

    def vigilar(self, pagina: Page) -> None:
        """Inyecta el oyente en una pagina y engancha su consola."""
        pagina.on("console", lambda m, p=pagina: self._al_mensaje(p, m))
        # `add_init_script` cubre las navegaciones futuras; el `evaluate` cubre
        # lo que ya esta cargado ahora mismo.
        try:
            pagina.add_init_script(_GUION)
        except Exception as exc:  # noqa: BLE001
            log.debug("No se pudo registrar el init script: %s", exc)
        try:
            pagina.evaluate(_GUION)
        except Exception as exc:  # noqa: BLE001 - p. ej. pagina en blanco
            log.debug("No se pudo inyectar en la pagina actual: %s", exc)

    def vigilar_contexto(self, context: BrowserContext) -> None:
        """Vigila las pestanas actuales y las que se abran despues."""
        for pagina in context.pages:
            self.vigilar(pagina)
        context.on("page", self.vigilar)

    def cerrar(self) -> None:
        try:
            self._fh.close()
        except Exception:  # noqa: BLE001
            pass
