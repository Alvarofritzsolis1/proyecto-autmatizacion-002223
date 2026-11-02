# GALANT en VPS Contabo (Ubuntu 22.04 / 24.04)

**Estado:** esta rama prepara el despliegue, pero no instala nada en tu VPS.
Esta rama contiene la versión VPS con interfaz renovada (dos áreas de carga)
y el lector híbrido 19.3 integrado desde PR #26, pero **no está en main**.
Para usarla en Contabo debes clonar ESTA rama y reconstruir la imagen Docker.
No dar por validado todo el OCR antes de comparar PDF reales.
No subir PDFs privados a GitHub.

## Instalacion facil en un solo comando (recomendado)

Si ya tienes Docker y clonaste la rama VPS, en el servidor:

```bash
cd /opt/galant
git fetch origin
git pull --ff-only origin deploy/contabo-vps-seguro-20261102
bash deploy/galant-facil.sh
```

El asistente muestra estas opciones:

1. **Prueba privada** (sin DNS). Arranca GALANT en 127.0.0.1:18501,
   sin publicar el puerto 8501. En **Windows PowerShell**, abrir una
   segunda sesion con `ssh -L 18501:127.0.0.1:18501 root@89.117.144.140`
   y visitar `http://localhost:18501`. Mantener SSH abierta.
   Este modo usa tunel seguro, pero sin contrasena web: no compartir el
   puerto local ni subir documentos laborales hasta validar privacidad.
2. **Publicar HTTPS** SOLO cuando `galant.dpdns.org` resuelva **unicamente**
   a 89.117.144.140 y exista un hash de Caddy en `.env`. El asistente
   aborta en caso contrario y no publica un acceso inseguro.
3. **DNS**: muestra la IP publica sin modificar DigitalPlat.
4. **Estado**: muestra contenedores y resultado DNS.

**OJO:** el panel DigitalPlat puede mostrar "Aplicado a servidores DNS"
aunque el DNS publico permanezca en 185.27.134.160. Es posible que el
hosting gratuito conserve una delegacion NS distinta de la zona donde
editaste el registro. Antes de cambiar mas datos DNS, contrasta el
servidor autoritativo y la delegacion:

```bash
sudo apt install -y dnsutils
dig +trace galant.dpdns.org A
dig @1.1.1.1 galant.dpdns.org A +short
dig @8.8.8.8 galant.dpdns.org A +short
```

El mismo registro A debe resolverse desde los NS realmente delegados.
No reemplazar NS por una IP. Si el hostname delega a los DNS del
hosting gratuito, editar su zona DNS o cambiar la delegacion al
servicio DNS que realmente contiene tu registro A.

## Arquitectura

Navegador -- HTTPS + contraseña --> Caddy (puertos 80/443 públicos) -->
Streamlit/Python (8501 SOLO privado en la red Docker) --> Tesseract,
RapidOCR/ONNX, PyMuPDF y exportación Excel.

No usar el `.devcontainer/devcontainer.json` para producción:
contiene parámetros inseguros que desactivan CORS/XSRF. Esta imagen los
activa expresamente y declara el dominio real del navegador.

## 1. Datos del servidor (SIN compartir contraseñas)

En https://my.contabo.com abre Control de VPS. Anota en privado:
IPv4, sistema operativo, núcleos vCPU, RAM, almacenamiento y credenciales.
Si es Windows Server, detente: esta guía supone **Ubuntu Linux**.
Conviene 4 vCPU / 8 GB RAM para OCR de varios PDF, según cantidad de
páginas y concurrencia. Una instancia menor puede funcionar, pero
requiere medir uso real. La potencia NO repara errores lógicos de OCR.

## 2. Conectar desde Windows

En PowerShell (Windows):

```powershell
ssh root@IP_PUBLICA_DEL_VPS
```

Verificar huella SSH antes de aceptarla (consola/panel de Contabo).
La contraseña no se ve al escribir. Ya dentro de Ubuntu:

```bash
cat /etc/os-release
nproc
free -h
df -h
sudo apt update && sudo apt upgrade -y
sudo apt install -y git ca-certificates curl ufw fail2ban
sudo adduser galantadmin
sudo usermod -aG sudo galantadmin
```

En Windows crea una clave SSH con `ssh-keygen -t ed25519` (no compartir
la clave privada). Copia **solamente la pública** a
`/home/galantadmin/.ssh/authorized_keys` en el VPS con permisos
`700` para `.ssh` y `600` para `authorized_keys`, ambos propiedad
de `galantadmin`. En una NUEVA ventana PowerShell confirma que funciona
`ssh galantadmin@IP_PUBLICA_DEL_VPS` antes de cerrar la sesión root
o deshabilitar acceso por contraseña.

## 3. Firewall (dos capas)

Desde Ubuntu:

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

En el panel Contabo, si activas su firewall de red, autoriza TCP
**22, 80 y 443** antes de aplicarlo. Preferir SSH 22 solo desde tu IP
administrativa si tienes IP estable. **No abrir 8501**, 8000, ni otros
puertos del OCR. Una vez comprobado el acceso por llave, se puede
deshabilitar `PermitRootLogin` y `PasswordAuthentication`, comprobando
`sudo sshd -t` y manteniendo una sesión alternativa abierta.

Docker advierte que sus puertos publicados pueden omitir reglas de UFW;
por eso aquí la aplicación no usa `ports:`, solo `expose:`, y la
segunda defensa es el firewall de red de Contabo.

## 4. Docker (repositorio oficial, como usuario galantadmin)

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
```

No agregues usuarios sin necesidad al grupo `docker`: da acceso
prácticamente equivalente a root. Usa `sudo docker ...`.

## 5. Elegir dominio y apuntar DNS

Necesitas controlar un dominio/subdominio con registro **A** hacia la IPv4
de Contabo. Ejemplo: `galant.tu-dominio.cl -> IP_PUBLICA`.
En Windows puedes comprobar:

```powershell
nslookup galant.tu-dominio.cl
```

No uses un subdominio de otro proveedor si este no te permite cambiar
su DNS. Sin un nombre DNS válido, la emisión HTTPS pública puede fallar.
Caddy obtiene y renueva el certificado al ver el DNS correcto y los
puertos TCP 80/443 abiertos.

## 6. Descargar el proyecto preparado (rama VPS actualizada)

Conectado por SSH como **galantadmin**:

```bash
sudo mkdir -p /opt/galant
sudo chown "$USER":"$USER" /opt/galant
git clone -b deploy/contabo-vps-seguro-20261102 https://github.com/Alvarofritzsolis1/proyecto-autmatizacion-002223.git /opt/galant
cd /opt/galant
git status --short --branch

# Si ya habías clonado esta rama antes de la mejora:
# cd /opt/galant
# git fetch origin
# git pull --ff-only origin deploy/contabo-vps-seguro-20261102
# Si clonaste main, primero selecciona la rama:
# git fetch origin
# git switch --track origin/deploy/contabo-vps-seguro-20261102
cp .env.example .env
chmod 600 .env
```

Por seguridad `.env` no se incluye en Git ni en la imagen Docker.

## 7. Contraseña de GALANT (HASH, NO texto claro)

Genera contraseña robusta con tu administrador de contraseñas. Después
genera un hash bcrypt **interactivamente** (evita guardarla en historial):

```bash
sudo docker run --rm -it caddy:2-alpine caddy hash-password
```

Escribe la contraseña cuando la solicite y copia SOLO el hash resultante.
Edita `.env` (en el VPS):

```bash
nano /opt/galant/.env
```

Sustituye `GALANT_DOMAIN`, `GALANT_USER` y `GALANT_AUTH_HASH`.
**El hash debe quedar entre comillas simples**, como en el ejemplo,
porque contiene símbolos `$`. Jamás envíes el archivo `.env` ni
credenciales por chat o GitHub. La autenticación básica es adecuada
como primera barrera para uso privado reducido; para equipos grandes,
se debe evaluar SSO/MFA, perfiles y auditoría de accesos.

## 8. Arrancar el servicio

```bash
cd /opt/galant
sudo docker compose config --quiet
sudo docker compose build
sudo docker compose up -d
sudo docker compose ps
sudo docker compose logs --tail=60 galant
sudo docker compose logs --tail=60 caddy
```

`docker compose config --quiet` valida la configuración sin imprimir
variables sensibles en pantalla. Abre `https://galant.tu-dominio.cl`
en tu navegador; debe solicitar usuario y contraseña.
`curl -I https://galant.tu-dominio.cl` normalmente devuelve
`401 Unauthorized` sin contraseña; es lo esperado.

## 9. Verificar dependencias y OCR realmente instalados

```bash
sudo docker compose exec galant tesseract --list-langs
sudo docker compose exec galant python -c "import fitz, pytesseract, cv2, rapidocr, onnxruntime, streamlit; print('IMPORTACIONES OCR OK')"
sudo docker compose exec galant python -m compileall -q app.py fonasa_runtime.py f301_lector.py
sudo docker compose ps
sudo docker stats --no-stream
```

Debe figurar `spa` y `eng` en Tesseract. Prueba primero con
**PDF sintéticos sin RUT ni datos laborales reales**. Después, con el
acceso restringido, valida PDFs reales con consentimiento y
comparación manual de páginas, período, folio, nombres, días, pagos
y XLSX. Una prueba de salud HTTP NO garantiza la exactitud del OCR.

## 10. Operación, fallos, versiones y respaldo

```bash
# Diagnóstico (evita publicar logs si contienen datos personales):
sudo docker compose logs -f --tail=100 galant
sudo docker compose logs -f --tail=100 caddy

# Estado del servidor:
free -h
df -h
sudo docker stats --no-stream

# Detener y reiniciar (sin eliminar los volúmenes de certificados/modelos):
sudo docker compose down
sudo docker compose up -d
```

Para actualizar después de revisión de una PR:
`git fetch --all`, seleccionar commit/versión validada,
`sudo docker compose build` y `sudo docker compose up -d`.
No ejecutar `docker compose down -v` salvo decisión consciente:
elimina volúmenes, incluido cache OCR y certificados de Caddy.
Conserva el SHA anterior (`git rev-parse HEAD`) y snapshots/backups
del VPS antes de cambios. No automatices el despliegue de `main`
sin una barrera de pruebas y aprobación humana.

## Solución de problemas

- **SSH no conecta:** comprobar IP, estado VPS, reglas Contabo/UFW,
  usuario y puerto 22. Nunca cerrar la única sesión antes de validar llave.
- **502 / página vacía:** `sudo docker compose ps` y logs de `galant`;
  errores de importación, RAM insuficiente o inicio de modelos.
- **HTTPS no funciona:** DNS A, puertos TCP 80/443, Caddy logs,
  `.env` y políticas del firewall Contabo.
- **401:** comportamiento normal antes de ingresar credenciales.
- **Streamlit se queda cargando / falla subida:** comprobar dominio
  `STREAMLIT_BROWSER_SERVER_ADDRESS` y puerto externo 443; NO
  desactivar CORS o XSRF para ocultar el problema.
- **OCR no reconoce el PDF:** revisar si tiene capa de texto,
  rotación, calidad de escaneo, memoria, logs sanitizados y
  páginas faltantes. No etiquetar como impago un fallo del lector.
- **Contenedor muere (OOM):** ver RAM, `docker stats`, logs y límites
  de páginas/concurrencia. Medir antes de subir recursos.

## Privacidad y alcance

GALANT procesa documentos de trabajadores. Mantener el repositorio
público SIN PDF, RUT, remuneraciones ni tokens; proteger acceso,
conexión y backups. Los documentos no se envían por defecto a una API
OCR de pago; los modelos RapidOCR pueden descargar archivos de modelos
al iniciar por primera vez. La aplicación **no verifica pagos ante
Previred ni bancos**, solo evidencia documental. Cambiar de Streamlit
Cloud a VPS **no cambia la exactitud lógica de GALANT**.

Fuentes:
- https://help.contabo.com/es/support/solutions/articles/103000271271-
- https://docs.contabo.com/docs/network-services/firewall/
- https://docs.docker.com/engine/install/ubuntu/
- https://docs.streamlit.io/deploy/tutorials/docker
- https://docs.streamlit.io/knowledge-base/deploy/remote-start
- https://caddyserver.com/docs/caddyfile/directives/basic_auth
