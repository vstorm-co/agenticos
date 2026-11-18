---
source_sha: "40e46eb28642"
---

# Auf Kubernetes deployen { #deploy-on-kubernetes }

`charts/agenticos` installiert API, Worker und Konsole aus veröffentlichten Images.
Vorausgesetzt werden externes PostgreSQL mit pgvector, Redis/Valkey und ein
vorhandener S3-Bucket. Das Chart installiert keine Datenbanken und erstellt keine
Backups. `appVersion` legt die Standardversion der Images fest. Andere Releases
lassen sich mit `image.tag`, unveränderliche Images mit `image.backendDigest`
und `image.frontendDigest` festlegen.

Backend-Images vor 1.63.0 erwarten gemeinsame temporäre Ingest-Dateien und
werden von diesem Chart nicht unterstützt.


## Kubernetes und OpenShift { #kubernetes-and-openshift }

Kubernetes plant und verwaltet Container. Red Hat OpenShift ist eine
Kubernetes-Plattform mit zusätzlichen Komponenten und Richtlinien, darunter
Security Context Constraints (SCC), SELinux-Integration und Routes. Dasselbe Chart
ist der Ausgangspunkt für beide Plattformen. Ein erfolgreicher Kubernetes-Test
validiert weder diese OpenShift-Komponenten noch die Identitäts- und
Speicherintegration eines Cloud-Anbieters.

| Bereitstellung | Nachweise und ausstehende Prüfungen |
| --- | --- |
| Kubernetes mit Helm | Reproduzierbarer kind-Smoke-Test unten; öffentlichen Ingress und NetworkPolicy-Durchsetzung im eigenen Cluster prüfen |
| OpenShift mit Helm | Lokales OpenShift 5.0.0 bestand restricted-v2, Helm-Lebenszyklus, HTTPS Routes, WSS und NetworkPolicy-Durchsetzung; eigenen Cluster und Speicher separat prüfen |
| Argo CD auf lokalem OpenShift | Argo CD Core 3.6.1 bestand Full-Sync-Installation, Migrationsverweigerung, Konfigurationsupgrade und kompatiblen Git-Revert auf demselben Datenbankschema |
| Sandbox und OIDC | Optionale Integrationen mit eigener Konfiguration und separaten Abnahmetests unten |

## Kompatibilität und Grenzen { #compatibility-and-limits }

Der reproduzierbare Test nutzt kind 0.33.0, Kubernetes 1.37.0 und Helm 4.3.1.
Er prüft eingeschränkte Pod-Security-Zulassung, schreibgeschützte Root-Dateisysteme,
beliebige numerische UIDs, Migrationen, Anmeldung, die Antwort eines veröffentlichten
Agenten, S3-Upload, Ingestion und einen dauerhaften Hintergrundlauf. Das Modell
ist eine deterministische Protokoll-Testkomponente; Verfügbarkeit und Antwortqualität
eines kostenpflichtigen Anbieters werden damit nicht nachgewiesen.

**OpenShift Local wurde getestet** mit CRC 2.65.0, OpenShift 5.0.0
(Kubernetes 1.36.5), Helm 4.3.1 und Anwendungs-Images 1.80.0. API, Worker und
Konsole liefen unter `restricted-v2` mit vom Namespace zugewiesenen UIDs und
schreibgeschützten Root-Dateisystemen. Weder `anyuid`, privilegierte SCCs noch
Node-Sockets wurden freigegeben. `values-openshift.yaml` überlässt UID und
`fsGroup` der SCC. Andere OpenShift-Versionen, Azure-Integration und
Speichertreiber sind damit nicht validiert.

Das Basis-Chart enthält weder Sandbox-Daemon noch Browser-Dienst oder
Artefakt-Renderer und mountet keinen Docker-Socket. Containerausführung,
Computer-/Browserbedienung und Rendering bleiben ohne ihre jeweiligen externen
Dienste nicht verfügbar. Verwenden Sie die [Sandbox-Konfiguration](sandbox.md)
und den Vault; mounten Sie nicht `/var/run/docker.sock` eines Nodes in Anwendungspods.

## Externe Dienste vorbereiten { #prepare-external-services }

Erstellen Sie Datenbank und Benutzer `agenticos` auf PostgreSQL mit pgvector.
Die Migrationsidentität muss die Erweiterung vector anlegen dürfen; alternativ
installiert sie der Datenbankadministrator vorher. Gewähren Sie der Anwendung
Zugriff auf ihre eigene Datenbank, Redis-Datenbank und den Bucket. Siehe
[externe Dienste und Verbindungszahlen](scaling.md).

Erstellen Sie den Bucket vor dem Bootstrap: Auch Avatare der Startagenten werden
dort gespeichert. Die Standardverschlüsselung ist `sse-s3`.
`storage.encryption: sse-kms` benötigt außerdem `storage.kmsKeyId`. Test-MinIO ohne
KMS nutzt `none`; dies empfiehlt keine unverschlüsselte Produktionsspeicherung.

Erstellen Sie über Ihre Secret-Verwaltung **vor dem Helm-Aufruf** ein Secret im
Anwendungs-Namespace. Es benötigt unabhängige, mit `openssl rand -hex 32` erzeugte
Werte für `SECRET_KEY`, `API_KEY`, `VAULT_MASTER_KEY` sowie `POSTGRES_PASSWORD`.
Bewahren Sie diese Schlüssel bei Upgrades auf. Eine Änderung des Vault-Schlüssels
ist eine [Schlüsselrotation](secrets.md), keine Neuinstallation: Er entschlüsselt
gespeicherte Organisationszugangsdaten. Ergänzen Sie bei Bedarf `REDIS_PASSWORD`
und für statische S3-Zugangsdaten das Paar `FILE_STORAGE_S3_ACCESS_KEY` /
`FILE_STORAGE_S3_SECRET_KEY`. Bei Workload Identity bleiben beide S3-Schlüssel weg.

Das Chart verwendet ein vorhandenes Service Account ohne automatisches Mounten
des API-Tokens. Setzen Sie für Workload Identity `serviceAccountName` und
konfigurieren Sie dort die Token-Projektion/Annotationen des Anbieters. Auch
Migrationshooks verwenden dieses Konto. Modellschlüssel bleiben Organisationssecrets
im Vault des Produkts.

Für `postgres.sslMode: verify-full` (Standard) oder `verify-ca` erstellen Sie
das Secret aus `trust.existingSecret` mit dem Datenbank-CA-Zertifikat unter dem
Schlüssel `postgres-ca.crt`. Das Chart mountet es schreibgeschützt in Migration,
API und Worker und setzt `PGSSLROOTCERT`. `trust.postgresCaKey` wählt einen anderen
Dateinamen. Für eine private Redis-CA ergänzen Sie ein kombiniertes öffentliches/
privates CA-Bundle und nennen dessen Schlüssel in `trust.sslCaKey`; das setzt
`SSL_CERT_FILE`. Behalten Sie öffentliche CAs für Modellanbieter im Bundle.
Andere SDK-Einstellungen wie `AWS_CA_BUNDLE` können über `extraEnv` denselben
Mount referenzieren.

## Installation { #install }

Verwenden Sie das Chart aus dem Repository-Tag des gewünschten Releases.
Erstellen Sie eine `cluster-values.yaml` mit Konfiguration, ohne Zugangsdaten:

```yaml
existingSecret: agenticos-runtime
public:
  siteUrl: https://app.example.com
  apiUrl: https://api.example.com
  websocketUrl: wss://api.example.com
postgres:
  host: postgres.internal
  database: agenticos
  user: agenticos
  sslMode: verify-full
trust:
  existingSecret: agenticos-trust
  postgresCaKey: postgres-ca.crt
redis:
  host: valkey.internal
  ssl: true
storage:
  bucket: agenticos-files
  region: eu-central-1
  # endpoint: https://s3.example.com
  # pathStyle: true
image:
  tag: "1.80.0"
trustedProxy:
  enabled: true
  namespaceLabels:
    kubernetes.io/metadata.name: ingress-system
  podLabels:
    app.kubernetes.io/name: your-ingress-controller
ingress:
  enabled: true
  className: your-ingress-class
  siteHost: app.example.com
  apiHost: api.example.com
  tls:
    - secretName: agenticos-tls
      hosts: [app.example.com, api.example.com]
```

```bash
helm lint charts/agenticos --strict -f cluster-values.yaml
helm upgrade --install agenticos charts/agenticos \
  --namespace agenticos --create-namespace -f cluster-values.yaml \
  --wait --timeout 15m
kubectl -n agenticos exec deployment/agenticos-agenticos-api -- agenticos cmd bootstrap
```

[Installation](install.md) erklärt Bootstrap-Zugangsdaten und Anbieter-Konfiguration.
Erstellen Sie den Namespace vor dem Runtime-Secret, falls er noch fehlt. Für
private Registries setzen Sie `imagePullSecrets`. Wenden Sie gerenderte Charts
nicht mit `kubectl apply` an: Das umgeht Helms Migrationsreihenfolge.

Verwenden Sie zwei öffentliche Hostnamen wie beim
[Compose-Deployment](deploy.md#why-two-hostnames). Der Ingress-Controller muss
WebSocket-Upgrades, ausreichend lange Leerlauf-/Request-Zeitlimits und die erlaubten
Uploadgrößen unterstützen. Setzen Sie seine Annotationen über
`ingress.annotations`. TLS übernimmt ein vorhandenes Zertifikats-Secret oder ein
Zertifikatscontroller. Auf OpenShift können Sie den Ingress deaktivieren und zwei
eigene Routes bereitstellen.

Begrenzen Sie Netzwerkverkehr mit Cluster-Richtlinien: Die Konsole erreicht die
API; API und Worker erreichen PostgreSQL, Redis, S3 sowie ausdrücklich konfigurierte
Anbieter/externe Dienste. Veröffentlichen Sie keine Datenbank- oder Worker-Ports.

Öffentlicher Ingress benötigt `trustedProxy.enabled: true` und nicht leere
Namespace-/Pod-Labelselektoren des Controllers. Ersetzen Sie das Beispiel durch
die tatsächlichen Labels Ihres geschützten Controllers. Das aktiviert
`RATE_LIMIT_TRUST_FORWARDED_FOR` zusammen mit NetworkPolicies: Nur der Controller
erreicht die Konsole; die API akzeptiert zusätzlich Konsolen-Pods dieses Releases.
Verwenden Sie ein CNI mit NetworkPolicy-Durchsetzung und veröffentlichen Sie die
Dienste nicht direkt. Schützen Sie diese Namespaces vor nicht vertrauenswürdigen
Pods. Ohne Richtliniendurchsetzung darf Header-Vertrauen nicht aktiviert werden.

Genau ein vertrauenswürdiger Proxy muss den echten Client an `X-Forwarded-For`
anhängen. Der Limiter liest die letzte Adresse; die Konsole bewahrt den Header
bei Auth-Proxy-Aufrufen. Fügt ein CDN/Load Balancer einen Hop hinzu, normalisieren
Sie die verifizierte Clientadresse am Edge. Der ClusterIP-Test validiert weder
Ihren Ingress-Controller noch das CNI. Prüfen Sie Isolation und Header vor
Produktionsverkehr. Externe Routes/Proxys benötigen dieselben Einstellungen.

## S3-Zugangsdaten und Bootstrap-Diagnose { #s3-credentials-and-bootstrap-troubleshooting }

S3 bezeichnet das Speicherprotokoll, keine Pflicht zur Nutzung von AWS. Für einen
kompatiblen Dienst wie MinIO setzen Sie `storage.endpoint`, `storage.bucket`,
`storage.region` sowie `storage.pathStyle` und Verschlüsselung nach Anbietervorgabe.
Die native API von Azure Blob Storage ist kein S3-Endpunkt; dieses Chart benötigt
einen S3-kompatiblen Dienst.

Statische Zugangsdaten gehören in das durch `existingSecret` benannte Secret,
unter den exakten Schlüsseln `FILE_STORAGE_S3_ACCESS_KEY` und
`FILE_STORAGE_S3_SECRET_KEY`. API, Worker und Migration laden es über `envFrom`.
Schreiben Sie Schlüssel weder unter `storage` oder `extraEnv` noch in Git oder
öffentliche Diagnosekommentare. Eine Workload-Identität muss eine vom S3-Client
verstandene Zugangsdatenkette bereitstellen; eine Azure-Cluster-Identität allein
liefert keine S3-Zugangsdaten.

`botocore.exceptions.NoCredentialsError` bei `agenticos cmd bootstrap` bedeutet,
dass der S3-Client beim Speichern eines Startagent-Avatars keine Zugangsdaten fand.
Die Datenbanktransaktion wird zurückgerollt; „Created owner“ belegt keinen Commit.
Korrigieren Sie das Secret, starten Sie API und Worker zum Neuladen der Umgebung
neu, warten Sie auf Bereitschaft und wiederholen Sie Bootstrap. Prüfen Sie Bucket,
Endpunkterreichbarkeit, TLS-Vertrauen und Schreibrechte separat. Geben Sie zur
Diagnose niemals Secret-Werte aus.

## OpenShift-Installation und beschreibbare Verzeichnisse { #openshift-installation-and-writable-directories }

Erstellen Sie zuerst Projekt, Laufzeit-Secret und Service Account. Behalten Sie
für die folgenden Befehle den Release-Namen `agenticos` bei. Laden Sie das
Kandidatenprofil vor den clusterspezifischen Werten und lassen Sie UID- und
Gruppeneinstellungen ungesetzt:

```bash
oc new-project agenticos
helm upgrade --install agenticos charts/agenticos --namespace agenticos \
  -f charts/agenticos/values-openshift.yaml -f cluster-values.yaml \
  --wait --timeout 15m
oc -n agenticos get pods
oc -n agenticos get pods -o 'custom-columns=NAME:.metadata.name,SCC:.metadata.annotations.openshift\.io/scc'
```

Prüfen Sie die zugelassene SCC auf die beabsichtigte restriktive Richtlinie.
Beheben Sie Rechtefehler nicht mit `anyuid`, privilegierten SCCs oder einem
beschreibbaren Root-Dateisystem. Das Frontend mountet beschreibbare `emptyDir` unter
`/tmp` und `/app/.next/cache`; Backend-Mounts stehen in `templates/_helpers.tpl`.
Ein `router-cache`-Fehler benötigt den **exakten absoluten Pfad**, Image-Tag/Digest,
OpenShift-Version, zugelassene SCC und bereinigte Logs. Cache außerhalb dieser
Mounts ist vom Chart nicht abgedeckt. Übermounten Sie nicht ganz `/app/.next`,
da sonst die gebaute Anwendung verborgen wird.

Bei `ingress.enabled: false` stellen Sie zwei HTTPS-Routes zu API- und
Frontend-Services bereit, beide mit benanntem Port `http`. Setzen Sie
`public.siteUrl`, `public.apiUrl` und `public.websocketUrl` auf externe Adressen.
Konfigurieren Sie Router-Timeouts, WebSockets, Upload-Limits, geschützte
Router-Selektoren unter `trustedProxy` und wirksame NetworkPolicies.
TLS-Terminierung allein bestätigt keine korrekte Client-Adressweitergabe.

## Migrationsreihenfolge in Argo CD { #argo-cd-migration-ordering }

Argo CD rendert Helm-Templates und führt kein `helm upgrade` aus. Seine
[Helm-Hook-Zuordnung](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/#helm-hooks)
bildet den Migrations-Job dieses Charts aus `pre-install` und `pre-upgrade` auf
`PreSync` ab; `before-hook-creation` ermöglicht einen erneuten Versuch beim nächsten
Sync. Namespace, Secrets und Service Account müssen **vor** dieser Phase bestehen,
außerhalb dieser Application oder aus einem abgeschlossenen Bootstrap-Schritt.

Führen Sie einen vollständigen Application-Sync aus und bestätigen Sie den
Migrationserfolg vor Deployment-Änderungen. Selektiver Sync überspringt Hooks.
Argo-CD-Hook-Annotationen ändern die Helm-Hook-Verarbeitung; mischen Sie keine
Lebenszyklen ohne Tests. Application- und Helm-Release-Name sollten übereinstimmen,
sofern Sie nicht das Argo-CD-Tracking gezielt so konfigurieren, dass die
Instanzselektoren dieses Charts erhalten bleiben.

Ein Git-Revert rollt keine Datenbank zurück. Argo CD implementiert Helm
`pre-rollback` nicht; ein vollständiger Sync des älteren Charts nutzt seinen
eigenen PreSync-Pfad. Prüfen Sie Migrationsfehler mit Rollout-Verweigerung,
erfolgreiches Upgrade und kompatiblen Revert mit Ihrer Argo-CD-Version vor
automatischer Synchronisierung. Helm und Argo CD dürfen nicht konkurrierende
Verwalter desselben Releases sein.

Für OpenShift das Profil als Helm-**Wertedatei** in Argo CD laden:

```yaml
helm:
  releaseName: agenticos
  valueFiles:
    - values-openshift.yaml
```

Dies ist `spec.source.helm` für den Quellpfad `charts/agenticos`; ergänzen Sie die
nicht geheimen Cluster-Einstellungen und vorhandenen Secret-Verweise wie oben.
Verlassen Sie sich nicht auf Inline-`valuesObject`-Nullwerte, um Standard-UIDs
oder `fsGroup` zu entfernen. Im lokalen Test erreichten sie Helm nicht wie
beabsichtigt. Die Profildatei behob die SCC-Ablehnung von UID/Gruppe 1000 ohne
erweiterte Berechtigungen.

Lokales Argo CD Core 3.6.1 bestand den ersten vollständigen Sync, PreSync-Fehler mit unveränderten Deployment-Spezifikationen, ein Konsolen-Konfigurationsupgrade und einen kompatiblen Git-Revisions-Revert auf demselben Datenbankschema. Der Controller durfte nur im Test-Namespace schreiben und nutzte [`resource.respectRBAC: strict`](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/). Er erhielt weder `anyuid` noch privilegierte SCC-Nutzung. Dies validiert weder den Red Hat OpenShift GitOps Operator noch ein Datenbank-Downgrade.

## OIDC- und Sandbox-Konfiguration { #oidc-and-sandbox-configuration }

Die lokale OIDC-Einrichtung behält die installierten Helm-Image-Tags und Digests für Backend und Konsole bei; die Anmeldungskonfiguration wählt kein anderes Anwendungsimage aus.

Nicht geheime OIDC-Backend-Einstellungen gehören in das oberste `extraEnv`,
`OIDC_CLIENT_SECRET` in `existingSecret`. Aktivieren Sie den Anmeldeknopf separat:

```yaml
extraEnv:
  OIDC_ISSUER: https://identity.example.com/realms/company
  OIDC_CLIENT_ID: agenticos
  OIDC_REDIRECT_URI: https://api.example.com/api/v1/oauth/oidc/callback
frontend:
  extraEnv:
    OAUTH_PROVIDERS: oidc
    OIDC_DISPLAY_NAME: Company SSO
```

`frontend.extraEnv` ist ab Chart-Version `0.1.1` verfügbar; ältere Charts ignorieren
die Option. Es enthält öffentliche Konsoleneinstellungen, niemals das Client-Secret.
Chartverwaltete Backend- und öffentliche URLs haben Vorrang vor doppelten
Frontend-Umgebungsschlüsseln. Registrieren Sie den exakten Callback beim
Identitätsanbieter. Prüfen Sie Knopf, Weiterleitung, Callback, bestätigte
E-Mail-Claim, Organisationszugriff, Abmeldung und Registrierungsbeschränkungen.
[Generisches OIDC](configuration.md#single-sign-on-generic-oidc) beschreibt
anbieterspezifische Claims und Einstellungen. Passwort-Smoke-Tests prüfen kein SSO.

Betreiben Sie für Sandbox-Werkzeuge einen separaten OpenSandbox-Server und
registrieren Sie URL, Image und Vault-Schlüssel unter **Settings → Sandboxes →
Connections**. Das Basis-Chart installiert ihn nicht. Der lokale OpenShift-Test
nutzte Server/Controller/execd/Gateway 1.2.1, Kubernetes BatchSandbox und Secure
Access. Ein echtes Werkzeug schrieb eine Datei; der nächste Lauf verband sich
wieder und las sie. Die Verbindungsprüfung führte einen POSIX-Shell-Befehl aus.
Geprüft wurden Endpunkt-Authentifizierung und eingeschränkte Workloads, nicht
gVisor, VM-Isolation, Egress-Richtlinien, Browser oder Rendering.

Das Server-Chart des Anbieters 1.2.1 deklariert Container-Port 80. Im eingeschränkten
Test setzte `configToml` den Wert `server.port = 8080`;
`scripts/kubernetes/opensandbox_ports.py` änderte den benannten HTTP-Container-Port
auf 8080 und behielt Service-/Probe-Verweise bei. Dieser ausführbare Post-Renderer
benötigt Helm 3 (getestet 3.22.1); Helm 4 benötigt ein Post-Renderer-Plugin. Die
Workload-Vorlage mountete private `emptyDir`-Volumes unter `/workspace` und `/tmp`
und überließ UID/Gruppen der SCC. Secure Access nutzte das private Gateway und ein
separates Keyring-Secret. Dies sind Anbieter-Einstellungen, keine AgenticOS-Chart-Werte.

**Die Bereinigung benötigt die Korrektur der Konversationslöschung aus dieser Änderung.**
Release 1.80.0 entfernte Workspace-Referenzen vor dem Einreihen der Remote-Löschung.
Der Kandidaten-Handler wurde auf diesem Image geprüft: Das Löschen der Konversation
entfernte Sandbox und Pod. Der Image-Tag allein belegt die Korrektur nicht.
Dateibrowser/Download für OpenSandbox über die Workspace-Archiv-API der Konsole sind
nicht implementiert; Dateiwerkzeuge des Agenten nutzen einen eigenen Pfad.
Siehe [Sandbox-Konfiguration](sandbox.md).

Das Löschen autorisiert den Zugriff, sperrt die Konversation und prüft den Zugriff erneut, bevor Workspace-Zeilen entfernt werden. Kontolöschung und Workspace-Bereinigung halten dadurch dieselbe Sperrreihenfolge ein: zuerst das übergeordnete Objekt. Ausstehende Löschungen und ihre Übergabe nach dem Commit bleiben bei einem Rollback geschützt.

## Gesundheit, Speicher und Kapazität { #health-storage-and-capacity }

Die API nutzt `/api/v1/health/live` für Start/Liveness und
`/api/v1/health/ready` für Datenbank-/Redis-Bereitschaft. Worker prüfen ihre
Datenbank-Heartbeat-Datei. Die Konsole nutzt `/login` für Start/Bereitschaft und
einen lauschenden Socket für Liveness. Ein langsamer Anbieter ist kein Prozessausfall.
Jeder Workload erhält 60 Sekunden zum Beenden; der Worker nimmt keine neuen Jobs
an und beendet laufende Arbeit oder gibt sie an die Queue zurück.

Ressourcen stehen getrennt in `api.resources`, `worker.resources`,
`frontend.resources` und `migration.resources`. Der Speicher der Ingest-Kinder
kommt zum Elternprozess hinzu. Stimmen Sie `extraEnv.WORKER_INGEST_CHILDREN` und
`extraEnv.WORKER_INGEST_MEMORY_MB` mit dem Pod-Limit ab. Skalieren Sie über `api.replicas`,
`worker.replicas` und `frontend.replicas`; berücksichtigen Sie die Datenbankpools
jedes zusätzlichen Prozesses.

Dateien liegen dauerhaft in S3. Für die Ingestion lädt der Worker eine eigene
Kopie herunter; gemeinsame Dateisysteme oder RWX-Claims sind nicht nötig.
Caches und Staging liegen auf begrenzten `emptyDir`-Volumes, deren Verlust erwartet
wird und die kein Backup sind. Ein getöteter Ingest-Prozess kann bis zum Ersetzen
des Pods eine temporäre Datei hinterlassen; normaler Abschluss, Parserfehler und
Abbruch entfernen die Kopie. Lokale Verzeichnis-Sync-Quellen müssen dem ausführenden
Worker zugänglich sein; das Chart mountet keine Betreiberverzeichnisse.

## Upgrade und Rollback { #upgrade-and-rollback }

Sichern Sie vorher PostgreSQL, S3 und Runtime-Schlüssel. Prüfen Sie Release Notes
und die Migrationskompatibilität mit alter und neuer Anwendung. Vor Installation
oder Upgrade führt ein Job `agenticos db upgrade` aus. Scheitert er, verändert
Helm die Deployments nicht. Fehlgeschlagene Jobs bleiben zur Diagnose erhalten:

```bash
kubectl -n agenticos logs job/agenticos-agenticos-migrate
helm history agenticos -n agenticos
```

Sichern Sie Logs vor dem nächsten Versuch: Der nächste Hook löscht den alten Job.
Führen Sie keine gleichzeitigen Upgrades desselben Releases aus, verwenden Sie
nicht `--no-hooks` und starten Sie nach einer gescheiterten Migration keine neuen
Pods manuell. Teilweise ausgeführte Migrationen erfordern eine Betreiberentscheidung;
Helm macht Datenbank-Nebenwirkungen nicht rückgängig.

Rolling Upgrades erfordern kompatible Schemas und Queue-Jobs, solange alte
Prozesse laufen. Bei inkompatiblen Änderungen stoppen Sie Traffic, lassen aktive
Arbeit auslaufen, skalieren alle drei Deployments auf null, sichern und aktualisieren
im Wartungsfenster. Prüfen Sie Bereitschaft und einen echten Agentenlauf vor der
Wiederfreigabe.

Beim ersten Upgrade eines vorhandenen S3-Deployments auf 1.63.0 lassen Sie die
Ingestion auslaufen und ersetzen Worker vor der API, oder nutzen Sie ein
Wartungsfenster. Neue API-Prozesse schreiben nicht mehr die gemeinsamen Kopien,
die alte Worker erwarten. Lokaler Speicher behält den gemeinsamen Verzeichnispfad.

`helm rollback agenticos REVISION -n agenticos --wait --timeout 15m` stellt die alte
Anwendung nur wieder her, wenn ihr Migrationshook die aktuelle Datenbank akzeptiert.
Das Schema wird nicht zurückgesetzt. Erkennt das alte Image die neue Revision
nicht, verweigert der pre-rollback-Hook den Austausch der Pods. Stellen Sie bei
Bedarf laut Release Notes ein passendes Datenbankbackup sowie kompatible Objekte
und Schlüssel bewusst wieder her. `helm uninstall` entfernt die Anwendung;
externe Datenbanken, Bucket und Runtime-Secret bleiben betreibereigen.

## Lokale Validierung und Abnahme { #local-validation-and-acceptance }

Beide Plattformen lassen sich lokal testen, benötigen aber getrennte Cluster.
Nutzen Sie kind für Kubernetes und [OpenShift Local (CRC)](https://crc.dev/docs/getting-started/)
für echtes OpenShift. `oc` auf einem kind-Cluster ergänzt weder SCC noch Routes.
CRC unterstützt Apple silicon im OpenShift-Preset, nicht im OKD-Preset.
Das [aktuelle Minimum](https://crc.dev/docs/installing/) für OpenShift beträgt
vier physische CPU-Kerne, 10,5 GB freien Arbeitsspeicher und 35 GB Festplatte,
vor zusätzlicher Anwendungskapazität. Betreiben Sie auf knappen Laptops nicht beide
Cluster gleichzeitig.

Der Kubernetes-Smoke-Test erstellt wegwerfbare pgvector-, Valkey-, MinIO- und
Modellprotokoll-Testdienste; AWS-Konto und kostenpflichtiger Modellschlüssel sind
unnötig. `SMOKE_IMAGE_TAG` fixiert das getestete Release für beide Images.
`SMOKE_BACKEND_IMAGE` und `SMOKE_FRONTEND_TAG` überschreiben das jeweilige Image
für Tests von Quellcode-Builds.

```bash
python3 scripts/kubernetes/test_chart.py
SMOKE_IMAGE_TAG=1.80.0 scripts/kubernetes/run-smoke.sh
```

Der automatische Konsolentest bestätigt nur die OIDC-Anzeigeeinstellungen und
kontaktiert keinen Identitätsanbieter. Der Modell-Testdienst prüft das Run-Protokoll,
nicht die Modellqualität. Der Smoke-Test nutzt ClusterIP-Portweiterleitung und
validiert daher weder öffentliches TLS, WebSockets über Router, CNI-Durchsetzung
noch Argo CD.

Installieren Sie für OpenShift Local CRC von Red Hat und beschaffen Sie Ihr eigenes
Pull-Secret. Bereiten und starten Sie dann das OpenShift-Preset auf dem Host:

```bash
crc config set preset openshift
crc setup
crc start --cpus 6 --memory 13312 --disk-size 45 \
  --pull-secret-file /path/to/pull-secret
```

`crc setup` konfiguriert Host-Netzwerk und Virtualisierung und kann Administratorrechte
benötigen. Folgen Sie den CRC-Anmeldeanweisungen mit einer separaten kubeconfig.
Prüfen Sie vor Änderungen den ausgewählten Cluster. Bereiten Sie erreichbare externe
Datendienste, Secrets und Service Account wie oben vor und installieren Sie mit dem
OpenShift-Profil. Die kind-Testabhängigkeiten ersetzen auf OpenShift keine Prüfung
restriktionskompatibler Dienste. Stoppen Sie den lokalen Cluster danach mit `crc stop`.

Protokollieren Sie Image-Digests, Chart-Revision, Cluster- und Argo-CD-Versionen,
zugelassene SCC, Befehle, Ergebnisse und bereinigte Fehlerlogs. Prüfen Sie vor einer
Erfolgsaussage über diesen Bereitstellungsweg:

- Migration vor Workload-Änderung; ein absichtlicher Migrationsfehler verhindert den
  Rollout. Kompatibles Upgrade und Revert erhalten die Daten.
- API, Worker und Konsole bleiben unter der vorgesehenen restriktiven Richtlinie
  bereit; Frontend-Navigation und Uploads erzeugen keine Schreibschutzfehler.
- Bootstrap, Anmeldung, Agent-Antwort, Upload, Ingestion und dauerhafter Job funktionieren.
- Beide öffentlichen HTTPS-Adressen, WebSockets, Upload-Limits, Weiterleitung und
  Netzwerkisolation funktionieren über den tatsächlichen Ingress oder die Routes.
- OIDC funktioniert mit gewähltem Anbieter, notwendigen Claims und Registrierungsregeln;
  Sandbox-Dateien überleben mehrere Turns, die Bereinigung funktioniert.
- Bei Argo CD Installation, fehlgeschlagene Migration, Upgrade und Revert durch
  vollständige Syncs wiederholen; ein Helm-Lauf validiert kein GitOps.

Ein lokaler OpenShift-Erfolg gilt für diese Version und Konfiguration. Azure-Identität,
Azure-Netzwerk, Speichertreiber und die Argo-CD-Einrichtung des Nutzers benötigen
weiterhin Tests in dessen Umgebung. Unvollständige Punkte als ungetestet melden,
nicht als bestanden.

### Gemessene lokale OpenShift-Validierung { #measured-local-openshift-validation }

Der Basistest bestand Bootstrap, Anmeldung, deterministischen Agentenlauf,
S3-Upload, Worker-Ingestion über pgvector und dauerhaften Hintergrundjob. Ein
Migrationsfehler stoppte Helm ohne Änderung der Deployment-Spezifikationen;
Upgrade und kompatibles Rollback auf demselben Schema bestanden. HTTPS Routes
mit Zertifikatsprüfung bestanden BFF-Anmeldung, Secure/HttpOnly-Cookies,
serverseitiges Seitenrendering sowie authentifizierten WSS-Upgrade und Ping.
Ein fremder Namespace konnte keinen der geschützten Services direkt erreichen.
Dies misst weder vollständige Client-Weiterleitungsketten noch maximale Upload-Größen.

Keycloak 26.8.2 bestand Discovery, PKCE, signierte Token-Prüfung, einmaligen
Konsolen-Codeaustausch, Organisationszugriff und Logout/Refresh-Widerruf über TLS
Routes. Unbestätigte E-Mail, nicht erlaubte Domain und Registrierung ohne Einladung
wurden abgewiesen. Dies validiert generisches OIDC, nicht Microsoft Entra oder Azure.
Serverseitige Seitenprüfungen reproduzieren den gemeldeten `router-cache`-Pfad nicht
und ersetzen keine interaktive Navigation durch alle Bildschirme.

Der Basislauf benötigte **6 CPUs, 13 GiB VM-RAM und eine virtuelle 45-GB-Platte**.
Mit CRCs Minimum von 10.5 GB konnten die Migrations-Pods dieser Fixtures nicht
geplant werden. Erweiterte Integrationen liefen nacheinander: Das Sandbox-SDK
fordert 2 GiB je Workspace an. Planen Sie zusätzliche Kapazität und Reserve für
Rolling Updates; 13 GiB belegt diesen Basistest und ist keine Produktionsdimensionierung.

Nach dem CRC-Start Python mit PyYAML, `oc`, `helm` und separatem Kubeconfig verwenden:

```bash
export KUBECONFIG="$HOME/.crc/machines/crc/kubeconfig"
scripts/kubernetes/run-openshift-smoke.sh
python3 scripts/kubernetes/local_integrations.py --kubeconfig "$KUBECONFIG" routes
python3 scripts/kubernetes/local_integrations.py --kubeconfig "$KUBECONFIG" oidc
```

Der Basis-Runner verweigert vorhandene Test-Namespaces; der Integrationshelfer
verlangt deren Eigentumslabels und verweigert andere APIs als CRC. Test-Namespaces
und private temporäre Dateien bleiben zur Prüfung erhalten. `sandbox_probe.py`
benötigt einen separat vorbereiteten Anbieter-Stack gemäß obiger Konfiguration;
der Basis-Runner installiert ihn nicht. Nach der Prüfung nur selbst erstellte
Namespaces/Anbieter-Ressourcen und das angezeigte temporäre Zertifikatsverzeichnis
entfernen, danach CRC stoppen. Das Pull Secret bleibt privat.

## Test reproduzieren { #reproduce-the-test }

Installieren Sie Docker, kubectl 1.37.0, kind 0.33.0, Helm 4.3.1 und Python mit PyYAML.
Führen Sie im Repository `python3 scripts/kubernetes/test_chart.py` und danach
`scripts/kubernetes/run-smoke.sh` aus. Das Skript erstellt und löscht einen eigenen
kind-Cluster, verwendet eine eigene kubeconfig und ersetzt keinen vorhandenen
Cluster. Es nutzt nicht Ihren aktuellen Kubernetes-Kontext. Die Ports 18000 und
13000 müssen frei sein.

Bauen Sie vor dem ersten Release dieser Änderung das Backend aus dem Quelltext
und setzen Sie `SMOKE_BACKEND_IMAGE=agenticos-smoke-backend:ci` und
`SMOKE_FRONTEND_TAG=1.62.8`, wie im Kubernetes-Workflow. Geprüft werden auch eine
gescheiterte Migration, ein erfolgreiches Upgrade, ein Rollback bei gleichem Schema
und ein Rollout mit beliebiger UID. Die Ein-Knoten-Testdatenbanken und der Bucket
sind keine Produktionsmanifeste. CI protokolliert Werkzeugversionen und Image-IDs.
`SMOKE_KEEP_CLUSTER=true` behält den Cluster zur Diagnose; löschen Sie ihn danach
mit `kind delete cluster --name agenticos-smoke`.
