# OutWarp — Fallos de arquitectura y plan de solución

**Repo:** https://github.com/fcrespo07/OutWarp.git
**Contexto:** análisis hecho clonando y leyendo el repo completo (server + client), no solo el README/ROADMAP. Este documento es un brief de trabajo, no una implementación — pensado para entregarlo a Claude Code y que desarrolle cada punto.

**Orden de prioridad recomendado:** #2 (claves privadas) > #1 (certificado) > #3 (updater). Lo desarrollo en el orden en que se descubrieron porque el hilo argumental ayuda a entenderlos, pero si solo hay tiempo para uno, es el #2: es el que compromete la propiedad de seguridad más básica del proyecto (que WireGuard es E2E) y el que menos depende de recursos externos (no requiere comprar nada, ni dominio, ni certificados).

---

## Fallo 1 — El certificado autofirmado contradice el propósito del proyecto

### El problema

`server/outwarp_server/crypto.py`, función `generate_tls_cert` (línea ~27):

```python
private_key = ec.generate_private_key(ec.SECP256R1())

subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, common_name),
])
...
_CERT_VALIDITY_DAYS = 3650  # ~10 años
```

Lo que genera:
- `x509.Name` con un solo atributo (CN). Sin O, sin C.
- Issuer == subject (autofirmado).
- SAN con una IP desnuda o un DNS.
- 3650 días de validez.
- Sin KeyUsage, sin EKU serverAuth, sin AIA/OCSP, sin SCTs de Certificate Transparency.

Un certificado real en el 443 hoy lleva cadena de CA, EKU, AIA, SCTs y ~90 días de validez. Cualquier middlebox que parsee el mensaje `Certificate` del handshake TLS lo detecta con una sola regla, sin descifrar nada.

La ironía: el README (`server` self-signed + client pinning, sin dominio) vende esto como ventaja para el caso de uso que el propio proyecto anuncia — *"corporate networks, captive Wi-Fi"* — que son justo las redes que inspeccionan TLS.

### La causa raíz: dos modelos de amenaza servidos por un solo transporte

| | Adversario | Necesita |
|---|---|---|
| **A** | Firewall que bloquea UDP por puerto (hotel, CGNAT, wifi público) | Salir por 443. **Ya funciona hoy.** |
| **B** | DPI que inspecciona TLS (instituto, empresa, censor) | Cert de CA real, dominio, fingerprint TLS creíble |

El autofirmado es óptimo para A e inútil para B. El ROADMAP (`ROADMAP.md`, sección "Planned — server side → Let's Encrypt + dynamic DNS branch") difiere la rama ACME+dominio con el argumento de que "needs a domain to validate end-to-end" — es al revés: esa rama debería ser el camino recomendado, y el autofirmado el fallback documentado para cuando no hay dominio.

### Consecuencias concretas encontradas en el código

**1. El pinning se salta en cualquier rung que no sea WSS directo.**

`client/outwarp/tunnel.py`, método `_try_strategy` (línea ~303):

```python
direct_wss = strat.scheme == "wss" and not strat.proxy
if direct_wss and strat.pin_mode != "none":
    ok, reason = self._check_pin(strat)
```

Y en `_check_pin` (línea ~322):

```python
except FingerprintMismatchError as exc:
    if strat.pin_mode == "tolerate" or self.allow_tls_intercept:
        log.warning(...)
        return True, ""
```

Con `pin_mode == "tolerate"` o el toggle de usuario `allow_tls_intercept` (existe en la UI: `set_tlsIntercept` en `client/outwarp/ui/shared.jsx`), un mismatch de huella se degrada a un warning en el log. La confidencialidad no se rompe (WireGuard sigue autenticando E2E vía Noise_IK con la pubkey del `.owcfg`), pero el handshake de WireGuard queda expuesto sin ningún disfraz TLS: mensajes de tamaño fijo (148/92 bytes), byte de tipo 0x01/0x02. Es exactamente el patrón que la herramienta existe para evitar.

**2. El rung de "camuflaje" puede ser contraproducente.**

`client/outwarp/fallback.py`, rung `S2 direct-camouflage`:

```python
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
```

Este UA se mete como cabecera HTTP sobre el ClientHello de rustls de wstunnel. El JA3/JA4 resultante no coincide con ningún Chrome real. Los sistemas de fingerprinting buscan específicamente esa incoherencia (UA dice Chrome, huella TLS dice otra cosa) — es una firma añadida, no camuflaje, sin mimicry real del ClientHello (uTLS).

### Plan de solución

**Opción 1 — Caddy + Let's Encrypt delante, con sitio señuelo (recomendada, empezar por aquí)**

Caddy escucha en 443 con cert real de Let's Encrypt, sirve un sitio normal en `/`, y hace `reverse_proxy` **solo** en el path secreto hacia wstunnel en localhost.

Resuelve de golpe:
- El cert deja de ser anómalo — idéntico a millones de certs Let's Encrypt reales.
- Sondeo activo: un censor que se conecta al endpoint ve una web real, no un 400 de wstunnel.
- El secreto compartido para el matcher de Caddy ya existe: `http_upgrade_path_prefix = secrets.token_urlsafe(32)` se genera en `setup_wizard.py` línea ~147.

**El cliente no necesita cambios de código.** `ConnectionStrategy` (`fallback.py`) ya tiene `sni_override`, `host_header`, `path_prefix`, `pin_mode` — un perfil detrás de Caddy es solo un modo de despliegue del servidor + una strategy provisionada en el `.owcfg` (mecanismo `S5.. server-provisioned` que ya existe en `build_ladder`).

Coste: dominio propio (fcrespo.tech ya existe y ya corre Caddy + Cloudflare Tunnel en PySrvr, según contexto conocido) + reescribir el wizard del servidor para bifurcar en dos ramas explícitas: "sin dominio (autofirmado, red no-hostil)" vs "con dominio (Caddy+ACME, red hostil)".

**Opción 2 — Cloudflare Tunnel (complemento, no sustituto)**

El endpoint pasa a ser una IP de Cloudflare compartida con medio internet — bloquearla tiene coste colateral para el censor. La arquitectura ya lo anticipa: `bypass_ips` en `StrategyConfig` y `all_bypass_ips()` en `fallback.py` existen precisamente para meter rangos anycast de un CDN.

Limitaciones a documentar: Cloudflare termina el TLS y ve los frames WebSocket (el payload WireGuard sigue cifrado extremo a extremo; los metadatos y el timing no); rendimiento peor para tráfico tipo VPN; los ToS del plan gratuito sobre tráfico no-HTTP son un riesgo operativo. Tratar como rung de fallback adicional en la escalera, no como camino principal.

**Opción 3 — uTLS / REALITY (futuro, no ahora)**

Arregla el JA3/JA4 de raíz, que ni la opción 1 ni la 2 tocan. Requiere cambiar el transporte (wstunnel usa rustls sin mimicry de ClientHello) — es reescribir una capa entera del proyecto, no un fix incremental.

**Acción inmediata de bajo coste mientras tanto:** quitar o desactivar el rung S2 (`direct-camouflage`) hasta que exista mimicry real de ClientHello. Sin él, el spoof de User-Agent solo añade una señal de detección.

**Checklist de implementación sugerido:**
- [ ] Bifurcar el wizard del servidor: pantalla explícita "¿Tienes un dominio?" → rama ACME vs rama autofirmada.
- [ ] Implementar generación de `Caddyfile` con `reverse_proxy` condicionado al `http_upgrade_path_prefix`, más un sitio señuelo estático.
- [ ] Adaptar `add_client`/`owcfg.py` para que el `.owcfg` generado en la rama ACID lleve `pin_mode: "none"` (no hace falta pinning con CA real) y el endpoint sea el dominio, no la IP.
- [ ] Documentar en README ambas ramas y cuándo usar cada una (en vez de presentar el autofirmado como la única vía).
- [ ] Quitar el rung `direct-camouflage` (S2) de `build_ladder` en `fallback.py`, o marcarlo explícitamente como experimental/desactivado por defecto.
- [ ] Añadir Cloudflare Tunnel como rung provisionado documentado (`S5..`), con nota de las limitaciones de metadatos arriba.

---

## Fallo 2 — El servidor genera y almacena las claves privadas WireGuard de los clientes

Este es, en mi opinión, más grave que el del certificado, y no aparece en `KNOWN_BUGS.md` ni en `ROADMAP.md`.

### El problema

`server/outwarp_server/operations.py`, función `add_client` (línea ~94):

```python
client_private_key, client_public_key = generate_wg_keypair()
```

Esa clave privada del *cliente* se genera **en el servidor** y se empaqueta en el `.owcfg`:

`server/outwarp_server/owcfg.py`, función `build_owcfg`:

```python
wireguard: dict[str, Any] = {
    "tunnel_name": "OutWarp",
    "client_address": client_address,
    "client_private_key": client_private_key,   # <- la privada del cliente
    "server_public_key": server_config.wg_public_key,
    ...
}
```

El comentario que justifica los permisos del fichero es honesto sobre el riesgo, pero solo cubre una parte de él:

```python
def write_owcfg(warpcfg: dict[str, Any], path: Path) -> None:
    """Write a .owcfg file with 0o600 permissions.

    The owcfg embeds the client's freshly-generated WireGuard private key, so
    a default-umask 0o644 ... leaves the key world-readable on multi-user
    boxes — a local user can rip it and impersonate that client.
    """
```

### Por qué es grave

- **El admin conoce la clave privada de cada cliente.** Puede suplantar a cualquiera. Toda la atribución en `list-clients` / `traffic_history.py` (que sí está bien diseñado: clava el historial por `public_key`, no por IP, evitando colisiones de atribución por reasignación de IP) queda indemostrable a nivel criptográfico, porque el propio servidor pudo haber generado tráfico "como si fuera" cualquier cliente.
- **El `.owcfg` es una credencial completa en tránsito**, no solo en reposo. Se entrega por Telegram, correo, USB, etc. La protección `0o600` en el disco del servidor cubre el punto **menos** expuesto de su ciclo de vida — el canal de entrega es mucho más vulnerable y no tiene ninguna protección.
- Rompe la propiedad de diseño básica de WireGuard: la clave privada nunca debería salir de la máquina que la usa.

### Plan de solución: flujo de enrolamiento con token de un solo uso

Mantener la UX de "un solo fichero que se importa" pero cambiar qué contiene:

1. `add-client` en el servidor ya no genera un par de claves para el cliente. Genera un **token de enrolamiento de un solo uso** (TTL corto, p. ej. 15 min, y `used_at` para invalidarlo tras el primer canje).
2. El `.owcfg` lleva ese token en vez de `client_private_key`.
3. Al importar, el cliente genera su propio par WireGuard localmente (ya existe `generate_wg_keypair` en el lado cliente — reutilizable) y llama a un endpoint nuevo del servidor para canjear el token, enviando solo su **clave pública**.
4. El servidor registra esa pubkey como peer autorizado y responde con el resto de la config (`server_public_key`, `client_address` asignada por `ip_pool.py`, `tls.cert_fingerprint_sha256`, etc.) — todo lo que no sea secreto del cliente.
5. El servidor nunca ve, ni almacena, ni transmite una clave privada de cliente.

**Infraestructura reutilizable ya existente en el repo:**
- `server/outwarp_server/web_auth.py` ya implementa exactamente el patrón necesario para el token: hash con scrypt (`n=2**15`, salt, `hmac.compare_digest`), y un `RateLimiter` con sliding-window lockout. Es el módulo mejor construido del repo — el token de enrolamiento es el mismo patrón con TTL y estado de un solo uso en vez de sesión persistente.
- `server/outwarp_server/api.py` ya expone endpoints — añadir uno de canje (`POST /enroll`) sigue el patrón existente.
- `owcfg.py` ya versiona con `schema_version` — el cambio de formato es retrocompatible por diseño (clientes viejos con formato v1 siguen funcionando hasta que se fuerce la migración).

**Checklist de implementación sugerido:**
- [ ] Nueva tabla/almacén para tokens de enrolamiento: `token_hash`, `created_at`, `expires_at`, `used_at`, `client_name` reservado.
- [ ] `add-client` genera el token en vez del par de claves; `build_owcfg` cambia de `client_private_key` a `enrollment_token`, bump de `schema_version`.
- [ ] Nuevo endpoint `POST /enroll` en `api.py`: recibe `{token, client_public_key}`, valida (hash + TTL + no usado), asigna IP vía `ip_pool.next_available_ip`, marca el token usado, devuelve el resto de la config.
- [ ] Cliente: en el flujo de importación de `.owcfg` (`client/outwarp/app.py` / lógica de import), detectar `schema_version` nuevo, generar el par localmente, llamar a `/enroll`, y solo entonces construir el config final local con su propia privada (que nunca se envía).
- [ ] Mantener compatibilidad con `.owcfg` v1 (formato antiguo con clave embebida) marcándolo como deprecado en el wizard/README, sin romper instalaciones existentes.
- [ ] Tests: extender `server/tests/test_owcfg.py` y `test_operations.py` para el nuevo flujo; añadir `test_api.py` para `/enroll` (token inválido, expirado, ya usado, happy path).

---

## Fallo 3 — El canal de auto-actualización tiene integridad pero no autenticidad

### El problema

`client/outwarp/updater.py`, función `verify_download` (línea ~195):

```python
def verify_download(path: Path, asset_name: str, checksums_url: str) -> tuple[bool, str]:
    """...
    - No checksums_url at all (legacy release): skip with ok=True.
    - Manifest URL present but fetch fails: ok=False.
    - Manifest fetched but asset isn't listed: ok=False.
    - Hash mismatch: ok=False.
    """
```

El razonamiento del fail-open (solo para releases legacy sin manifest) y fail-closed (si el fetch falla) está bien pensado — evita que un atacante que pueda tirar la red selectivamente para el manifest, degrade la verificación.

El hueco real: **`SHA256SUMS.txt` se publica en el mismo release de GitHub que el binario**, y se descarga por el mismo camino de confianza (`_LATEST_API = f"https://api.github.com/repos/{_REPO}/releases/latest"`). Esto protege contra descargas corruptas o truncadas. No protege contra un release publicado por quien controle la cuenta de GitHub (token robado, cuenta comprometida, ataque a la cadena de CI/CD) — el propio atacante publicaría el binario malicioso *y* su SHA256SUMS a juego.

Combinado con: el cliente auto-actualiza sin confirmación fuerte, y el instalador de Windows corre elevado y sin firma de código (el propio `ROADMAP.md` ya lo señala como pendiente, sección "Distribution → Code signing"). El vector completo: comprometer el token/cuenta de publicación en GitHub = ejecución de código elevado en todos los clientes con auto-update activo.

### Plan de solución

Firmar el manifest (o los propios binarios) con **minisign** o **cosign**, con la clave pública embebida en el código fuente del cliente (no descargada — de lo contrario el mismo problema se traslada un nivel). El updater verifica la firma del manifest *antes* de confiar en sus hashes.

Ventaja sobre el certificado de firma de código (Authenticode) que ya está en el ROADMAP: minisign/cosign es gratis y no depende de comprar nada ni de un proceso de verificación de identidad — es un paso independiente y más barato que se puede hacer antes.

A medio plazo: dar una fecha de caducidad a la rama "legacy sin manifest" (`ok=True` sin verificación) y pasarla a fail-closed una vez todos los releases en circulación tengan manifest firmado.

**Checklist de implementación sugerido:**
- [ ] Generar par de claves minisign/cosign para firmar releases; documentar el proceso de release (dónde vive la clave privada, quién firma).
- [ ] Embeber la clave pública en `client/outwarp/updater.py` (constante, no descargable).
- [ ] Firmar `SHA256SUMS.txt` en el pipeline de release (o firmar cada binario directamente, evaluar cuál es más simple de mantener).
- [ ] Nueva función `verify_manifest_signature()` en `updater.py`, llamada antes de `fetch_checksums()` confiar en el contenido.
- [ ] Tests: extender `client/tests/test_updater.py` con casos de firma válida/inválida/ausente.
- [ ] Añadir un aviso de deprecación en el flujo legacy (`ok=True, "no SHA256SUMS published"`) con fecha límite documentada en `ROADMAP.md`.

---

## Apéndice — Cosas verificadas y descartadas durante el análisis

Para que Claude Code no vuelva a investigar lo mismo:

- **`ip_pool.next_available_ip`** reasigna IPs libres de clientes revocados — en un primer vistazo parecía un riesgo de colisión de atribución. Verificado que **no lo es**: `server/outwarp_server/traffic_history.py` clava todo el historial (`snapshot`, `hourly_buckets`, `top_talkers`) sobre `public_key` como clave primaria compuesta (`PRIMARY KEY (ts, public_key)`), no sobre la IP. Diseño correcto, no requiere cambios.
- **`KNOWN_BUGS.md`** documenta 17 bugs ya resueltos con causa raíz y prevención por cada uno (B-001 a B-017) — buena disciplina de ingeniería, no aporta nada nuevo a este análisis pero es la referencia si se quiere ver el historial de decisiones ya tomadas.
- El `web_auth.py` del panel web (scrypt + `hmac.compare_digest` + rate limiter con sliding window) es el módulo con mejor postura de seguridad del repo — se referencia arriba como plantilla a reutilizar para el token de enrolamiento del Fallo 2.
