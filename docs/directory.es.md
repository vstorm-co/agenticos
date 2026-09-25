---
source_sha: "786dab540111"
---

# Inicio de sesión con el directorio y grupos { #directory-sign-in-and-groups }

Una empresa que usa Active Directory, OpenLDAP o FreeIPA ya sabe quién trabaja en
ella y a qué equipos pertenece cada persona. Esta página cubre las tres formas en
que AgenticOS puede aprovechar ese conocimiento. La gente puede iniciar sesión con
su cuenta del directorio. Un navegador unido al dominio puede iniciarle la sesión
con su ticket de Kerberos. Y los grupos del directorio pueden decidir a qué
organizaciones se une cada persona, con qué rol y en qué grupos está.

Lo componen tres piezas, y funcionan de forma independiente:

| Pieza | Qué hace | Quién la configura |
|---|---|---|
| [Grupos](#groups) | Conjuntos con nombre de miembros de una organización con los que se puede compartir un recurso | Los miembros con `members:manage`, en la consola |
| [Mapeos de grupos del directorio](#directory-group-mappings) | «Todos los de este grupo del directorio entran con este rol, en este grupo» | Los miembros con `members:manage` y `roles:manage` |
| [Inicio de sesión con el directorio](#signing-in-with-a-directory-account) | Inicio de sesión con contraseña por LDAP, e inicio de sesión con Kerberos (SPNEGO) | El operador, en `backend/.env` |

Los mapeos se aplican también a quienes inician sesión por
[OIDC](configuration.md#single-sign-on-generic-oidc), cuando el proveedor de
identidad informa de sus grupos. Si tu empresa ya tiene Keycloak o Entra ID delante
de su directorio, puede que no necesites en absoluto el inicio de sesión LDAP
nativo. Véase
[A través de un proveedor de identidad](#through-an-identity-provider-instead).

## Grupos { #groups }

Un grupo es un conjunto con nombre de miembros dentro de una organización:
*Finanzas*, *Equipo de soporte*, *Administradores de la plataforma*. Un agent, un
skill, una colección, un archivo de contexto, un secreto del vault o un artefacto
se comparten con un grupo igual que con una persona, desde el panel **Sharing**
del recurso. Una sola concesión llega entonces a todos los del grupo.

Una concesión a un grupo alcanza a quien esté en el grupo **en el momento en que se
comprueba el acceso**. Quien entre en el grupo el mes que viene alcanza el
recurso; quien salga deja de alcanzarlo. No hay nada que revocar persona a
persona.

Un grupo no lleva rol. Lo que un miembro puede hacer en la organización sigue
siendo el rol de su membresía, y un grupo solo añade las concesiones hechas a él.
El acceso efectivo sigue la regla descrita en
[Permisos](permissions.md#how-the-layers-combine):

```
effective access to one row = max(role scope, the person's grant, their groups' grants)
```

Cuando una persona alcanza una fila a través de varias concesiones, gana el nivel
más alto. Lectura por su propia concesión y edición por la de su grupo es edición.

| Acción | Quién puede |
|---|---|
| Listar los grupos y ver quién está en ellos | Cualquier miembro de la organización |
| Crear, renombrar o borrar un grupo; añadir o quitar personas | `members:manage` |
| Compartir un recurso con un grupo | Quien pueda editar ese recurso |

Los grupos están en **Organizations → Members → Groups**. Solo se pueden añadir
miembros de la organización, y quitar a alguien de la organización lo quita de
todos sus grupos. Borrar un grupo borra todas las concesiones hechas a él y todos
los mapeos del directorio que lo nombran.

## Mapeos de grupos del directorio { #directory-group-mappings }

Un mapeo dice qué significa un grupo del directorio dentro de una organización:

> Todos los de `CN=Finance,OU=Groups,DC=corp,DC=example,DC=com` son **member**
> aquí, y están en el grupo **Finanzas**.

Los mapeos están en **Organizations → Members → Directory**. Leerlos exige
`members:manage`. Crear o borrar uno exige `members:manage` y `roles:manage`,
porque un mapeo admite a gente y además le da un rol.

El rol está acotado igual que el de una invitación. Solo puedes mapear un grupo del
directorio a un rol que tu propio rol supere estrictamente. Nadie puede mapear un
grupo a `owner`, y un Admin no puede mapear un grupo a Admin. Borrar un mapeo exige
la misma autoridad, porque degrada a todos los que colocó.

### Qué pasa al iniciar sesión { #what-happens-at-sign-in }

Cada vez que alguien inicia sesión con LDAP, con Kerberos, o por OIDC con
[`OIDC_GROUPS_CLAIM`](#the-groups-claim-over-oidc) definido, sus grupos del
directorio se cotejan con los mapeos de todas las organizaciones:

1. **A una organización con un mapeo coincidente** se une, si todavía no es
   miembro, con el rol mapeado. La membresía queda marcada como **directory**.
2. **Una membresía del directorio** pone su rol al día con los mapeos.
3. **Entra en los grupos mapeados**, y sale de las pertenencias a grupos creadas
   por el directorio que ya no nombra ningún mapeo.
4. **Una membresía del directorio a la que no le queda ningún mapeo coincidente**
   se elimina, junto con las pertenencias de la persona a grupos de esa
   organización.

Los grupos se comparan sin distinguir mayúsculas de minúsculas ni espacios
alrededor, porque todo directorio los compara así.

Cuando varios mapeos coinciden en una organización, el rol es el primero de estos
que nombre cualquiera de ellos:

**admin → builder → operator → member → viewer**

Los roles no se ordenan por una sola línea de autoridad. Un builder y un operator
tienen cada uno algo que el otro no tiene, así que el orden se fija aquí en lugar
de deducirse.

### Lo que la sincronización nunca toca { #what-the-sync-never-touches }

La sincronización solo cambia las filas que creó ella misma. De eso se siguen
cuatro reglas:

- **Una membresía creada por un administrador conserva su rol.** Alguien invitado
  a mano conserva el rol que se le dio, aunque un mapeo coincida con él. Sigue
  entrando en los grupos mapeados.
- **Cambiar a mano el rol de un miembro del directorio se queda con la
  membresía.** Pasa a ser una membresía manual, y los inicios de sesión
  posteriores dejan su rol como está.
- **Una pertenencia a un grupo añadida a mano se queda** cuando el directorio
  sacaría a la persona de ese grupo.
- **Un owner nunca se degrada ni se elimina**, y ningún mapeo puede crear uno.
  La propiedad se mueve solo con **Transfer ownership**.

A una organización personal nunca se entra a través de un mapeo, y no se puede
crear un mapeo para una.

!!! warning "Borrar un mapeo elimina a las personas que colocó"

    La eliminación ocurre en el **siguiente inicio de sesión** de cada persona, no
    de inmediato. Para conservar a alguien después de borrar el mapeo que lo trajo,
    cambia antes su rol a mano. Eso se queda con la membresía.

### Los mapeos admiten cuentas nuevas { #mappings-admit-new-accounts }

Un mapeo cuenta como una invitación. En un despliegue `invite_only`, o en uno con
una lista de dominios permitidos, un primer inicio de sesión cuyos grupos coincidan
con el mapeo de cualquier organización crea la cuenta. Alguien que tiene a la vez
`members:manage` y `roles:manage` decidió que todos los de ese grupo tienen su
sitio allí. Un despliegue `closed` lo sigue rechazando. Véase
[Quién puede registrarse](deployment.md#who-may-register).

## Iniciar sesión con una cuenta del directorio { #signing-in-with-a-directory-account }

Define `LDAP_URL` y la página de inicio de sesión ofrece un formulario del
directorio. La gente teclea el nombre de usuario que usa en todas partes y su
contraseña del directorio. AgenticOS comprueba la contraseña con el bind estándar
en dos pasos:

1. Busca en `LDAP_USER_BASE_DN` con `LDAP_USER_FILTER`, usando la cuenta de
   servicio (`LDAP_BIND_DN`), exactamente una cuenta que coincida con el nombre de
   usuario.
2. Hace bind **como esa cuenta** con la contraseña tecleada. Solo el directorio
   comprueba la contraseña. Aquí no se guarda, ni se hashea, ni se registra en los
   logs.

La cuenta se indexa por el identificador estable del propio directorio:
`LDAP_ID_ATTRIBUTE`, `objectGUID` en Active Directory y `entryUUID` en OpenLDAP y
FreeIPA. No se indexa por la dirección, así que una persona que cambia de nombre
conserva su historial. En su primer inicio de sesión la cuenta se crea según la
[política de registro](deployment.md#who-may-register), y una cuenta existente con
la misma dirección queda vinculada a ella.

```bash
# backend/.env - Active Directory over LDAPS
LDAP_URL=ldaps://dc01.corp.example.com
LDAP_CA_CERT_FILE=/etc/ssl/certs/corp-ca.pem
LDAP_BIND_DN=CN=agenticos,OU=Service Accounts,DC=corp,DC=example,DC=com
LDAP_BIND_PASSWORD=...
LDAP_USER_BASE_DN=OU=Staff,DC=corp,DC=example,DC=com
LDAP_ID_ATTRIBUTE=objectGUID
```

```bash
# frontend - show the form on the sign-in page
OAUTH_PROVIDERS=ldap
LDAP_DISPLAY_NAME=Active Directory
```

Cada ajuste y su valor por defecto están en
[Configuración](configuration.md#directory-sign-in-ldap).

### Lo que el inicio de sesión rechaza { #what-the-sign-in-refuses }

| Se rechaza | Por qué |
|---|---|
| Una contraseña vacía | Un bind LDAP con un nombre y sin contraseña es un bind *no autenticado*, que muchos servidores aceptan (RFC 4513). Nunca llega al directorio |
| Dos cuentas que coinciden con un mismo nombre de usuario | Hacer bind como la que volviera primero podría iniciar la sesión de una persona como otra |
| Un nombre de usuario con sintaxis de filtro | Se escapa (RFC 4515), así que `*` no encuentra a nadie en lugar de a todo el mundo |
| Una cuenta sin dirección o sin identificador | La cuenta, la invitación y la política de registro se indexan todas por ellos |
| `ldap://` sin StartTLS | Envía todas las contraseñas en claro. El proceso se niega a arrancar salvo que `LDAP_ALLOW_PLAINTEXT=true` lo indique a propósito |

Un nombre de usuario erróneo y una contraseña errónea reciben la misma respuesta.
Un directorio caído, una cuenta de servicio rechazada y una búsqueda que el
directorio no pudo responder (un base DN erróneo, por ejemplo) se notifican como
que el directorio no está disponible. No se notifican como una contraseña errónea,
lo que mandaría a todas las personas de la empresa a restablecer la suya.

El certificado se verifica contra el almacén de confianza del sistema, o contra
`LDAP_CA_CERT_FILE` para una CA de empresa, y lo mismo el nombre del host. El
inicio de sesión tiene un límite de tasa por dirección y por nombre de usuario,
como el inicio de sesión con contraseña.

### Grupos desde el directorio { #groups-from-the-directory }

Por defecto, los grupos de una persona son los DN de su atributo `memberOf`. Un
directorio sin `memberOf` puede consultarse con una búsqueda en su lugar: define
`LDAP_GROUP_BASE_DN`, y `LDAP_GROUP_FILTER` con `{dn}` o `{username}` dentro. Para
los grupos anidados de Active Directory, busca con la regla de coincidencia que
sigue la cadena:

```bash
LDAP_GROUP_BASE_DN=OU=Groups,DC=corp,DC=example,DC=com
LDAP_GROUP_FILTER=(member:1.2.840.113556.1.4.1941:={dn})
```

Para dejar iniciar sesión solo a un grupo, ponlo en `LDAP_USER_FILTER`:
`(&(objectClass=user)(sAMAccountName={username})(memberOf=CN=AgenticOS Users,OU=Groups,DC=corp,DC=example,DC=com))`.

## Inicio de sesión integrado de Windows (Kerberos) { #integrated-windows-sign-in-kerberos }

En una máquina unida al dominio, un navegador que apunta a un host en el que confía
su política responde a `WWW-Authenticate: Negotiate` con un ticket de Kerberos. Con
`KERBEROS_ENABLED=true` la página de inicio de sesión ofrece un botón que inicia la
sesión de la persona con ese ticket, y nadie teclea una contraseña.

El ticket nombra un principal, `jane@CORP.EXAMPLE.COM`. AgenticOS lo resuelve a
través del directorio de arriba, con `LDAP_KERBEROS_FILTER`
(`(userPrincipalName={principal})` por defecto), a la **misma cuenta** a la que
llega el inicio de sesión LDAP con contraseña. Así que Kerberos necesita también
`LDAP_URL`, y el directorio decide la dirección y los grupos de la misma forma para
los dos.

Lo que hace falta:

1. **Una imagen construida con el extra `kerberos`.** `gssapi` se compila contra
   las bibliotecas de Kerberos del sistema, así que no está en la imagen por
   defecto:
   `docker build --build-arg EXTRAS="--extra kerberos" -f backend/Dockerfile .`
2. **Un service principal y su keytab.** En Active Directory, crea una cuenta de
   servicio, dale el SPN `HTTP/agenticos.corp.example.com` y exporta un keytab con
   `ktpass`. Móntalo en el contenedor del backend.
3. **Los ajustes del backend.**

    ```bash
    KERBEROS_ENABLED=true
    KERBEROS_KEYTAB=/etc/agenticos/http.keytab
    KERBEROS_SERVICE_PRINCIPAL=HTTP/agenticos.corp.example.com@CORP.EXAMPLE.COM
    ```

4. **El botón**, con `kerberos` en el `OAUTH_PROVIDERS` del frontend y
   `KERBEROS_DISPLAY_NAME=Windows sign-in` si quieres que se llame así.
5. **Una política del navegador** que le deje negociar con el host de la API. Eso
   significa la zona de intranet local en Windows, o `AuthServerAllowlist` para
   Chrome y Edge, o `network.negotiate-auth.trusted-uris` para Firefox.

El service principal tiene que nombrar el host por el que el navegador llega a la
**API**. Ese es `PUBLIC_API_URL`, porque la negociación ocurre allí, no en el host
de la consola.

Un navegador que no puede responder al desafío se devuelve directamente a la
página de inicio de sesión con una frase que lo dice. Eso cubre cualquier máquina
fuera del dominio, y cualquier navegador cuya política no incluya el host. Solo se
acepta un ticket aceptado en un único paso. NTLM no se ofrece.

## A través de un proveedor de identidad { #through-an-identity-provider-instead }

Si tu empresa ya pone un proveedor de identidad delante de su directorio, apunta
AgenticOS a él en su lugar, por [OIDC](configuration.md#single-sign-on-generic-oidc).
Usa su claim de grupos para los mapeos. El inicio de sesión nativo por LDAP y por
Kerberos deja entonces de hacer falta. Esta es también la respuesta para la
autenticación multifactor, que el inicio de sesión nativo no hace.

**Keycloak** federa los dos. En **User federation**, añade un proveedor **LDAP**
para tu directorio, y activa ahí **Allow Kerberos authentication** si quieres el
inicio de sesión integrado. Su **group-ldap-mapper** trae los grupos del
directorio. Después, dale al cliente de AgenticOS un mapper **Group Membership**
cuyo claim del token sea `groups`, y define:

```bash
OIDC_ISSUER=https://id.corp.example.com/realms/staff
OIDC_GROUPS_CLAIM=groups
```

El grupo del directorio del mapeo es entonces lo que Keycloak pone en el claim: la
ruta del grupo, como `/Finance`, o el nombre a secas si **Full group path** está
desactivado.

**Microsoft Entra ID**, con grupos sincronizados desde Active Directory, pone un
claim `groups` en el token en cuanto el registro de la aplicación tiene uno en
**Token configuration**. Por defecto lleva el id de objeto de cada grupo, y ese id
es lo que mapeas.

### El claim de grupos por OIDC { #the-groups-claim-over-oidc }

`OIDC_GROUPS_CLAIM` nombra el claim que lista los grupos de una persona. Sin
definir, los inicios de sesión por OIDC dejan las membresías como están.
Definido, cada inicio de sesión del propio proveedor del despliegue aplica los
mapeos exactamente como lo hace un inicio de sesión del directorio. El inicio de
sesión con Google nunca lo hace, porque solo el propio proveedor del despliegue es
de confianza para decir en cuáles de sus grupos está alguien.

El claim se lee del ID token, o del endpoint UserInfo cuando el token no lo lleva.
Un claim configurado que falta cuenta como **ningún grupo**. Keycloak y Okta omiten
una lista vacía en lugar de enviarla, y alguien a quien se quitó de su último grupo
tiene que perder lo que ese grupo le daba.

!!! warning "El exceso de grupos de Entra ID se rechaza"

    Pasados 200 grupos, Entra ID envía un puntero a Microsoft Graph en lugar de
    los grupos (`_claim_names`). Un token así no dice en qué grupos está la
    persona, así que el inicio de sesión se rechaza con una frase que pide la
    corrección. Leerlo como «ningún grupo» le quitaría todas las membresías que le
    dio el directorio, e ignorarlo conservaría algunas que quizá le haya quitado.
    Configura el registro de la aplicación para que envíe **groups assigned to the
    application**.

## Lo que esto todavía no hace { #what-this-does-not-do-yet }

- **Nada vuelve a comprobar el directorio entre inicios de sesión.** Desactivar una
  cuenta en el directorio detiene su siguiente inicio de sesión, y el siguiente
  inicio de sesión es cuando se vuelven a leer los mapeos. Una sesión ya abierta
  dura hasta que caduca su refresh token, que es `REFRESH_TOKEN_EXPIRE_MINUTES` y
  siete días por defecto. Para terminarla antes, desactiva la cuenta en
  **Admin → Users**, lo que la rechaza en todas partes a la vez. No hay SCIM ni
  sincronización programada del directorio.
- **Una cuenta del directorio todavía puede usar el restablecimiento de contraseña
  y el enlace mágico.** Van a la dirección de la cuenta, como los de cualquier otra
  cuenta. Si el directorio tiene que ser la única vía de entrada, mantén esas
  direcciones bajo el control de la propia empresa, como harías con las cuentas
  OIDC.
- **Sin SAML.** Un proveedor de identidad que solo habla SAML puede llegar a
  AgenticOS a través de Keycloak, que le habla SAML a él y OIDC a AgenticOS.
