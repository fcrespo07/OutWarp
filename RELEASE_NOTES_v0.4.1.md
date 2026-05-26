## Fix — actualizaciones in-app silenciosas

Esta versión corrige un bug en el auto-updater por el que actualizar desde la propia app **no reemplazaba realmente los binarios**: el cliente se cerraba, el instalador "se aplicaba", y al reabrir la app seguía siendo la versión anterior.

**Causa:** el cliente lanzaba el instalador con `ShellExecute` e inmediatamente iniciaba su propio cierre. El instalador, en `/VERYSILENT`, comprobaba el `AppMutex` (`Global\OutWarpClient`) antes de que el cliente terminara de soltar los locks sobre `outwarp.exe` y los `.pyd` de `_internal/`. Como en modo silencioso no hay diálogo de reintento, Inno Setup saltaba en silencio la copia de los archivos bloqueados y terminaba "ok". El `[Run] /AUTOUPDATE=1` relanzaba entonces el `outwarp.exe` viejo.

**Fix:** el cliente ahora spawnea un helper PowerShell desacoplado (heredando elevación, sin UAC extra) que hace `Wait-Process` sobre nuestro PID y sólo entonces lanza el instalador. Para cuando Inno comprueba el mutex, ya está liberado y todos los archivos se reemplazan limpiamente.

## ⚠ Importante para usuarios en v0.3.0 / v0.4.0

El bug vive **en el código que hace la actualización**, no en el destino. Si estás en v0.3.0 o v0.4.0, el botón "Actualizar" desde la app seguirá fallando de la misma forma al saltar a v0.4.1. **Necesitas instalar v0.4.1 a mano una vez** (descarga el `.exe` de abajo y ejecútalo). A partir de v0.4.1 las actualizaciones in-app funcionarán correctamente.

## Installers

- **`OutWarpSetup-0.4.1.exe`** — full installer (cliente + servidor). Úsalo para la primera instalación en máquinas que ejecuten ambos.
- **`OutWarpSetup-Client-0.4.1.exe`** — sólo cliente. Lo que descargará el auto-updater a partir de ahora.
- **`OutWarpSetup-Server-0.4.1.exe`** — sólo servidor.

`SHA256SUMS.txt` adjunto; el updater verifica la descarga contra él antes de lanzarla.

## Upgrade

- **v0.3.0 / v0.4.0 → 0.4.1**: descarga manual (ver arriba).
- **≥0.4.1 → versiones futuras**: detectado automáticamente desde Settings → Updates.
