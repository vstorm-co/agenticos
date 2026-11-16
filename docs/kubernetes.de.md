---
source_sha: "37f61b35dd4e"
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


## Kompatibilität und Grenzen { #compatibility-and-limits }

Der reproduzierbare Test nutzt kind 0.33.0, Kubernetes 1.37.0 und Helm 4.3.1.
Er prüft eingeschränkte Pod-Security-Zulassung, schreibgeschützte Root-Dateisysteme,
beliebige numerische UIDs, Migrationen, Anmeldung, die Antwort eines veröffentlichten
Agenten, S3-Upload, Ingestion und einen dauerhaften Hintergrundlauf. Das Modell
ist eine deterministische Protokoll-Testkomponente; Verfügbarkeit und Antwortqualität
eines kostenpflichtigen Anbieters werden damit nicht nachgewiesen.

**OpenShift ist noch nicht validiert.** `values-openshift.yaml` entfernt feste UIDs
und `fsGroup`, damit `restricted-v2` die Bereiche des Namespace zuweisen kann.
Prüfen Sie die Konfiguration auf Ihrer OpenShift-Version. Eine beliebige UID auf
Kubernetes validiert weder SCC-Zulassung noch SELinux, Routes oder Storage-Treiber.
Vergeben Sie keine `anyuid`- oder privilegierten SCCs und keinen Zugriff auf
Node-Sockets, um die Anwendung zum Starten zu bringen.

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
  tag: "1.63.0"
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
