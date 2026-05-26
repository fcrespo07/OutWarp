## Fix — instaladores slim (cliente / servidor) no instalaban nada

Esta versión corrige un bug crítico en los instaladores slim introducidos en v0.2.6: `OutWarpSetup-Client-X.Y.Z.exe` y `OutWarpSetup-Server-X.Y.Z.exe` ejecutaban el wizard, registraban el uninstaller y creaban el acceso directo "Desinstalar OutWarp"… pero **no copiaban ningún archivo de la aplicación**. El resultado era una entrada en "Aplicaciones instaladas" con solo el desinstalador funcional.

**Causa:** en `installer/windows/outwarp.iss`, la sección `[Types]` se compilaba únicamente para `Edition=full`. En las ediciones slim todos los `[Components]` se declaraban con `Flags: fixed` pero sin parámetro `Types:` y sin ninguna `[Types]` definida. Bajo esa combinación, Inno Setup nunca marca los componentes como seleccionados al instalar, por lo que cada `[Files]`, `[Icons]` y `[Tasks]` con `Components: client / wstunnel / wireguard` se filtraba — sobrevivían solo las entradas sin restricción de componente (uninstaller + su shortcut).

**Fix:** se añade un bloque `[Types]` con un tipo `full` para las ediciones slim, y `Types: full` a cada `[Components]`. El instalador full no cambia.

## ⚠ Importante para usuarios en v0.4.1 (instalación slim)

Si usaste `OutWarpSetup-Client-0.4.1.exe` y la app no se instaló, simplemente desinstala desde "Aplicaciones instaladas" y descarga **`OutWarpSetup-Client-0.4.2.exe`** abajo. El auto-updater desde la app no te ayudará aquí: para que funcione necesitas tener la app instalada primero.

Si tienes v0.4.1 instalada con el full installer (`OutWarpSetup-0.4.1.exe`), no estás afectado y el auto-updater funcionará normalmente.

## Installers

- **`OutWarpSetup-0.4.2.exe`** — full installer (cliente + servidor).
- **`OutWarpSetup-Client-0.4.2.exe`** — sólo cliente. Lo que descargará el auto-updater.
- **`OutWarpSetup-Server-0.4.2.exe`** — sólo servidor.

`SHA256SUMS.txt` adjunto; el updater verifica la descarga contra él antes de lanzarla.

## Upgrade

- **v0.4.1 (slim instalado correctamente) → 0.4.2**: auto-updater desde Settings → Updates.
- **v0.4.1 (slim que no instaló nada) → 0.4.2**: descarga manual.
