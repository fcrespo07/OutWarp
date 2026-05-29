# Handoff: OutWarp · TUI Linux

## Para Claude Code — lee esto primero

Este paquete contiene **el diseño y el plan de implementación** para añadir una TUI Textual a OutWarp en Linux. Es un bundle de design handoff: hay especificación visual + plan paso a paso, **no código fuente listo para copiar**.

### Qué hay aquí

| Archivo | Para qué sirve |
|---|---|
| `IMPLEMENTATION_PLAN.md` | **El plan que tienes que seguir.** 11 secciones, 6 fases. Está anclado al código real del repo (símbolos reales como `TunnelManager.phase`, `CheckResult.remediation_command`, etc.). Empieza por aquí. |
| `visual_spec/OutWarp TUI.html` | Mockup pixel-perfecto de las 8 pantallas finales. Ábrelo en un navegador para ver el resultado al que apunta cada `Screen` que implementes. |
| `visual_spec/tui-final.css` | CSS del mockup (sólo para que el HTML renderice). No es para portar — la TUI usa **Textual TCSS**, otra sintaxis. El plan tiene las reglas TCSS equivalentes. |

### Importante

- **No portes el HTML.** El HTML es solo una referencia visual de cómo se ve cada pantalla en una terminal — el código real es Python con [Textual](https://textual.textualize.io/) (clases `Screen`, `ModalScreen`, widgets como `DataTable`/`RichLog`/`Sparkline`).
- **No empieces la Fase 2 sin acabar la Fase 1.** El plan está pensado así por una razón: la Fase 1 extrae lógica de los CLI a módulos puros (`operations.py`, `traffic_history.py`, etc.) que las pantallas Textual consumen. Si haces la TUI primero, vas a duplicar lógica que luego tendrás que extraer igualmente.
- **Responde primero las 4 preguntas abiertas (Sección 11 del plan)** antes de tocar código. Son decisiones que afectan al diseño del backend.

## Contexto: dónde encaja esto

- El **repo de implementación** es `github.com/fcrespo07/OutWarp` (no este proyecto de diseño).
- El usuario ya tiene la CLI funcionando (`outwarp-cli` y `outwarp-server`). La TUI **reemplaza la GUI React/pywebview en Linux** (los comandos de CLI no cambian — la TUI los compone visualmente).
- Cliente y servidor son dos paquetes Python separados (`client/` y `server/` en el monorepo). Cada uno necesita su propio módulo `tui/`.

## Cómo orquestar la implementación

Cuando el usuario te diga "implementa esto":

1. **Lee** `IMPLEMENTATION_PLAN.md` entero antes de tocar nada.
2. **Confirma** las respuestas a las 4 preguntas abiertas con el usuario.
3. **Implementa Fase 1 completa** (backend changes, ningún archivo TUI todavía).
4. **Para** y deja que el usuario revise + mergee.
5. **Continúa** con Fase 2 (TUI cliente), después Fase 3 (TUI servidor), etc.

Cada fase tiene su lista de **Acceptance criteria** al final — úsala como definition of done antes de declarar la fase terminada.

## Mapa rápido del repo destino

```
OutWarp/
├── client/
│   ├── outwarp/
│   │   ├── cli.py              ← añadir subcomando `tui`
│   │   ├── tunnel.py           ← YA TIENE manager.phase (no inventes el enum)
│   │   ├── config.py
│   │   ├── logs.py             ← añadir tail_follow() async
│   │   ├── platforms/linux.py
│   │   └── tui/                ← NUEVO (Fase 2)
│   └── pyproject.toml          ← añadir extra [tui]
└── server/
    ├── outwarp_server/
    │   ├── cli.py              ← añadir subcomando `tui`
    │   ├── diagnostics.py      ← añadir checks Linux + fix_kind
    │   ├── server_manager.py   ← arrancar TrafficHistory.snapshot loop
    │   ├── operations.py       ← NUEVO (Fase 1) — extrae lógica de cli.py
    │   ├── traffic_history.py  ← NUEVO (Fase 1) — SQLite snapshots
    │   └── tui/                ← NUEVO (Fase 3)
    └── pyproject.toml          ← añadir extra [tui]
```

## Restricciones de compatibilidad (críticas)

La TUI corre en cualquier terminal Linux razonable. **No introduzcas**:
- Emoji (😀, 🎉, etc.). Solo glyphs BMP.
- `nerd-font` glyphs. No están en el resto de terminales.
- Dependencias de mouse — todo debe funcionar 100% por teclado.
- Tamaños fijos. El layout debe responder a resize y degradar a una columna en <100 cols.

Glyphs permitidos: caja `─│┌┐└┘├┤`, bloques `▁▂▃▄▅▆▇█`, formas `●○◐`, flechas `↑↓→←↵▸`.

## Si tienes dudas

- Mira el HTML del mockup para entender la composición visual deseada.
- Lee el código existente que el plan menciona (especialmente `client/outwarp/tunnel.py` y `server/outwarp_server/diagnostics.py`) antes de añadir nada.
- Si hay ambigüedad, **pregunta al usuario** — no inventes API ni comportamientos.
