# Paridad entre superficies

Fotografía del 2026-10-01 (fase 2, segunda pasada de pulido). Qué se puede hacer
desde cada superficie, qué huecos quedan y cuáles se cierran. Se actualiza al
cambiar una superficie, no a mano cada versión.

Regla: una superficie solo carece de algo si no tiene sentido en ella (la TUI no
dibuja gráficas de alta resolución, la CLI no es interactiva) o si el hueco está
aquí abajo con su decisión. Ampliar la CLI **ensancha la superficie que se
congela en 1.0**: esos huecos necesitan decisión del autor.

## Cliente

| Función | GUI | TUI | CLI |
|---|---|---|---|
| Importar perfil | sí | sí | `import` |
| Listar / cambiar / borrar perfil | sí | sí (`P`) | `profile` |
| Editar o restablecer un perfil | sí | sí | no |
| Conectar | sí | sí | `connect` (primer plano) |
| Desconectar / reconectar | sí | sí (`k`, `r`) | solo parando `connect` o el servicio |
| Ruta usada, servidor, WG, kill switch en el estado | sí | sí (PR del TUI cliente) | no (`status` no ve el túnel de otro proceso) |
| Ajustes (kill switch, idioma, servicio, UI) | sí | sí (`s`) | **no** |
| Registro: ver, filtrar | sí | sí | `logs` |
| Registro: exportar y vaciar | sí | sí (`x`, `c`) | no |
| Doctor | sí (Acerca de) | sí | `doctor` |
| Buscar e instalar actualización | sí | busca (`u`) | `update` |
| Servicio en segundo plano | sí | sí (ajustes) | `service` |

## Servidor

| Función | GUI | Panel | TUI | CLI |
|---|---|---|---|---|
| Añadir cliente + `.owcfg` / QR | sí | sí | sí (`a`, QR) | `add-client` |
| Revocar / rotar / desactivar / podar | sí | sí | sí | sí |
| Reiniciar servicios | sí | sí | sí (`r`) | `restart` |
| Parar / arrancar servicios | sí | sí | **no** | **no** (solo `restart`) |
| Doctor y arreglos automáticos | sí | sí | sí | `doctor` (sin arreglos) |
| Historial de tráfico | sí | sí | resumen 24 h | no |
| Renovar el certificado TLS | sí | sí | **no** | `renew-cert` |
| Probar el puerto desde fuera | sí | sí | sí (`p`) | no |
| Editar la configuración del servidor | sí | sí | no | no (solo `setup`) |
| Idioma | sí | sí | sí (`s`, PR del TUI servidor) | `OUTWARP_LANG` |
| Token de admin | n/a | n/a | n/a | `admin-token` |

## Cerrado en esta pasada

- Textos fijos en inglés de la CLI, el wizard, el doctor y las dos TUIs: ya van por i18n.
- TUI del cliente: ruta, servidor, WG y kill switch en el estado, selector de idioma.
- TUI del servidor: selector de idioma (`s`), probar el puerto (`p`), etiquetas traducidas y alineadas.

## Huecos abiertos (decisión del autor)

Tocan la CLI congelada o son pantallas nuevas; ninguno bloquea 1.0.

1. **CLI sin ajustes** (`outwarp settings get|set`, idioma y kill switch): ensancha la CLI. Descartado el 2026-10-01, queda para 1.x; hoy el idioma solo cambia desde GUI/TUI o con `OUTWARP_LANG`.
2. **Servidor sin parar/arrancar en CLI y TUI**: toca la CLI congelada. Descartado el 2026-10-01 (decisión del autor: sin ampliar la CLI antes de 1.0); queda para 1.x.

Los huecos 3 y 4 de la lista anterior (doctor en la GUI del cliente, actualizar y exportar el registro desde la TUI) se cerraron el 2026-10-01.
