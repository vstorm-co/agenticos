/**
 * What the console keeps on the device for when the network is gone (#2097),
 * sealed with a key the page can use but nobody can read out.
 *
 * One IndexedDB database per origin. Its key is an AES-GCM `CryptoKey` made
 * non-extractable and stored in the same database: IndexedDB keeps the key
 * object itself, which no script - this page's included - can export, so the
 * profile's files on disk hold only ciphertext. The database belongs to one
 * person in one organization. Opened for anybody else it is deleted first, and
 * signing out or switching organization deletes it outright (`wipeSealedStore`).
 */

const DATABASE = "agenticos-offline";
const META = "meta";
const SEALED = "sealed";
/** Bumped when a record's shape changes: a database from before is dropped, not read. */
const SCHEMA = 1;

interface Seal {
  owner: string;
  schema: number;
  key: CryptoKey;
}

interface SealedRecord {
  iv: Uint8Array<ArrayBuffer>;
  data: ArrayBuffer;
  savedAt: number;
}

/** What `get` hands back: the value, and when it was put there. */
export interface Kept<T> {
  value: T;
  savedAt: Date;
}

/** The browser's storage and cryptography - in tests, an in-memory IndexedDB and Node's WebCrypto. */
export interface DeviceApis {
  indexedDB: IDBFactory;
  subtle: SubtleCrypto;
}

function browserApis(): DeviceApis {
  return { indexedDB: globalThis.indexedDB, subtle: globalThis.crypto.subtle };
}

/**
 * A request's answer. A write is answered once it is in its transaction, and a
 * later transaction on the same connection sees it: IndexedDB runs them in order.
 */
function done<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function open(indexedDB: IDBFactory): Promise<IDBDatabase> {
  const request = indexedDB.open(DATABASE, 1);
  request.onupgradeneeded = () => {
    request.result.createObjectStore(META);
    request.result.createObjectStore(SEALED);
  };
  return done(request).then((db) => {
    // Another tab signing out deletes the database; this connection must let
    // go for the deletion to happen at all.
    db.onversionchange = () => db.close();
    return db;
  });
}

function remove(indexedDB: IDBFactory): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.deleteDatabase(DATABASE);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
    // Another tab still holds it open; the deletion completes when that tab
    // lets go, and nothing can open it in between.
    request.onblocked = () => resolve();
  });
}

/**
 * The records one console keeps, sealed: `Records` names each one and the shape
 * stored under it.
 *
 * The one writer of the database is `put`, typed by the same map, and a change
 * of shape bumps `SCHEMA` - which drops the database rather than reading it. So
 * a record comes back as the type it was put as; that is the invariant the
 * `get` below relies on in place of parsing what it decrypted.
 */
export class SealedStore<Records extends object> {
  private constructor(
    private readonly db: IDBDatabase,
    private readonly key: CryptoKey,
    private readonly subtle: SubtleCrypto,
  ) {}

  /**
   * The store for `owner` - one person in one organization. A database left by
   * anybody else, or by an older console, is deleted and a new key made.
   */
  static async open<Records extends object>(
    owner: string,
    apis: DeviceApis = browserApis(),
  ): Promise<SealedStore<Records>> {
    let db = await open(apis.indexedDB);
    const seal = await done<Seal | undefined>(db.transaction(META).objectStore(META).get("seal"));
    if (seal && seal.owner === owner && seal.schema === SCHEMA) {
      return new SealedStore(db, seal.key, apis.subtle);
    }
    if (seal) {
      db.close();
      await remove(apis.indexedDB);
      db = await open(apis.indexedDB);
    }
    const key = await apis.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, [
      "encrypt",
      "decrypt",
    ]);
    await done(
      db
        .transaction(META, "readwrite")
        .objectStore(META)
        .put({ owner, schema: SCHEMA, key } satisfies Seal, "seal"),
    );
    return new SealedStore(db, key, apis.subtle);
  }

  async put<K extends keyof Records & string>(name: K, value: Records[K]): Promise<void> {
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const plain = new TextEncoder().encode(JSON.stringify(value));
    const data = await this.subtle.encrypt({ name: "AES-GCM", iv }, this.key, plain);
    await done(
      this.db
        .transaction(SEALED, "readwrite")
        .objectStore(SEALED)
        .put({ iv, data, savedAt: Date.now() } satisfies SealedRecord, name),
    );
  }

  /** The record, or null when there is none or it is older than `maxAgeMs`. */
  async get<K extends keyof Records & string>(
    name: K,
    maxAgeMs?: number,
  ): Promise<Kept<Records[K]> | null> {
    const record = await done<SealedRecord | undefined>(
      this.db.transaction(SEALED).objectStore(SEALED).get(name),
    );
    if (!record) return null;
    if (maxAgeMs !== undefined && Date.now() - record.savedAt > maxAgeMs) {
      await this.delete(name);
      return null;
    }
    const plain = await this.subtle.decrypt(
      { name: "AES-GCM", iv: record.iv },
      this.key,
      record.data,
    );
    // See the class: only `put` writes, typed by the same map.
    const value = JSON.parse(new TextDecoder().decode(plain)) as Records[K];
    return { value, savedAt: new Date(record.savedAt) };
  }

  async delete(name: keyof Records & string): Promise<void> {
    await done(this.db.transaction(SEALED, "readwrite").objectStore(SEALED).delete(name));
  }

  /** The names of the records kept under `prefix`. */
  async names(prefix: string): Promise<string[]> {
    const keys = await done(this.db.transaction(SEALED).objectStore(SEALED).getAllKeys());
    return keys.filter((key): key is string => typeof key === "string" && key.startsWith(prefix));
  }

  close(): void {
    this.db.close();
  }
}

/** Delete everything kept, key and all. */
export function wipeSealedStore(apis: DeviceApis = browserApis()): Promise<void> {
  return remove(apis.indexedDB);
}
